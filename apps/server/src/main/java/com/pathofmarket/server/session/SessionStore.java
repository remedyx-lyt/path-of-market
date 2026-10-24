package com.pathofmarket.server.session;

import com.pathofmarket.server.config.SessionProperties;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * 研究会话的 JSONL 追加存储（M2-1）。参照 Pi SessionManager：每个会话一个文件，首行会话头，之后每行一个带 id/parentId 的条目。
 *
 * <p>Python 研究服务产生条目并按顺序提交；这里按会话串行追加并落盘，按条目 id 去重（重试不会写重复行），
 * 文件末尾若有写到一半的残行，先补换行再追加；读取时跳过无法解析的行。不覆盖、不修改已写入的行。
 */
@Component
public class SessionStore {
    private static final Pattern UUID_PATTERN = Pattern.compile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
    private static final Set<String> TYPES = Set.of("session", "event", "message", "context_edit", "report", "run_state", "continuation", "report_draft");

    private final Path directory;
    private final JsonMapper mapper;
    private final Map<String, Object> locks = new ConcurrentHashMap<>();
    private final Map<String, Set<String>> writtenIds = new ConcurrentHashMap<>();
    private final Map<String, String> sessionByRun = new ConcurrentHashMap<>();

    public SessionStore(SessionProperties properties, JsonMapper mapper) {
        this.directory = properties.path().toAbsolutePath().normalize();
        this.mapper = mapper;
        try {
            Files.createDirectories(directory);
        } catch (IOException error) {
            throw new UncheckedIOException("无法创建会话目录：" + directory, error);
        }
        // 启动时只读各文件的会话头与 runId，建立 runId → 会话索引；服务重启后旧任务链接仍能找到记录。
        try (Stream<Path> files = Files.list(directory)) {
            files.filter(f -> f.getFileName().toString().endsWith(".jsonl")).forEach(this::indexFile);
        } catch (IOException error) {
            throw new UncheckedIOException("无法读取会话目录：" + directory, error);
        }
    }

    /** 追加一批条目；返回实际写入的行数（已写过的 id 跳过）。新会话的第一条必须是会话头。 */
    public int append(String sessionId, List<JsonNode> entries) {
        requireId(sessionId);
        Path file = file(sessionId);
        synchronized (locks.computeIfAbsent(sessionId, key -> new Object())) {
            Set<String> written = writtenIds.computeIfAbsent(sessionId, key -> readIds(file));
            Set<String> staged = new HashSet<>(written);
            boolean empty = written.isEmpty();
            StringBuilder lines = new StringBuilder();
            int count = 0;
            for (JsonNode entry : entries) {
                String type = entry.path("type").asString("");
                String id = entry.path("id").asString("");
                if (!entry.isObject() || !TYPES.contains(type) || id.isEmpty() || id.length() > 80) {
                    throw new IllegalArgumentException("条目须为带 id 与已知 type 的对象");
                }
                if (empty && count == 0 && !"session".equals(type)) {
                    throw new IllegalArgumentException("新会话的第一条必须是会话头");
                }
                if ("session".equals(type) && !sessionId.equals(id)) {
                    throw new IllegalArgumentException("会话头 id 与会话不一致");
                }
                if (!staged.add(id)) continue;
                lines.append(mapper.writeValueAsString(entry)).append('\n');
                count++;
            }
            if (count > 0) {
                try {
                    write(file, lines.toString());
                } catch (RuntimeException error) {
                    // IO 可能只写完部分行；重试时从磁盘重建去重集合，不能把“准备写入”当成“已落盘”。
                    writtenIds.remove(sessionId);
                    throw error;
                }
                written.addAll(staged);
                for (JsonNode entry : entries) {
                    String runId = entry.path("runId").asString("");
                    if (!runId.isEmpty()) sessionByRun.put(runId, sessionId);
                }
            }
            return count;
        }
    }

    /** 读取会话的全部条目（跳过空行与无法解析的残行）；首条不是会话头时视为不存在。 */
    public Optional<List<JsonNode>> load(String sessionId) {
        requireId(sessionId);
        Path file = file(sessionId);
        if (!Files.exists(file)) return Optional.empty();
        List<JsonNode> entries = new ArrayList<>();
        try (Stream<String> lines = Files.lines(file, StandardCharsets.UTF_8)) {
            lines.forEach(line -> parse(line).ifPresent(entries::add));
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
        if (entries.isEmpty() || !"session".equals(entries.getFirst().path("type").asString(""))) return Optional.empty();
        return Optional.of(entries);
    }

    public Optional<String> sessionForRun(String runId) {
        return Optional.ofNullable(sessionByRun.get(runId));
    }

    /**
     * 从 JSONL 还原某次研究的任务快照（与 Python 任务接口同一结构），供重启后打开旧链接与回放过程。
     * 没有结束状态的运行视为中途中断，如实标为 failed。
     */
    public Optional<ObjectNode> snapshot(String runId) {
        return sessionForRun(runId).flatMap(this::load).map(entries -> buildSnapshot(runId, entries));
    }

    /** 最近的研究记录（按会话创建时间倒序），每条含研究对象、问题、状态与报告标题。 */
    public List<ObjectNode> recent(int limit) {
        List<ObjectNode> sessions = new ArrayList<>();
        for (String sessionId : Set.copyOf(sessionByRun.values())) {
            load(sessionId).ifPresent(entries -> sessions.add(summary(entries)));
        }
        sessions.sort(Comparator.comparing((ObjectNode s) -> s.path("createdAt").asString("")).reversed());
        return sessions.subList(0, Math.min(limit, sessions.size()));
    }

    private ObjectNode buildSnapshot(String runId, List<JsonNode> entries) {
        JsonNode header = entries.getFirst();
        ArrayNode events = mapper.createArrayNode();
        JsonNode report = null, state = null;
        String phase = "queued";
        int modelCalls = 0;
        for (JsonNode entry : entries) {
            if (!runId.equals(entry.path("runId").asString(""))) continue;
            switch (entry.path("type").asString("")) {
                case "event" -> {
                    JsonNode event = entry.path("data");
                    events.add(event);
                    if ("phase_changed".equals(event.path("type").asString(""))) phase = event.path("phase").asString(phase);
                    if ("model_finished".equals(event.path("type").asString(""))) modelCalls++;
                }
                case "report" -> report = entry.path("report");
                case "run_state" -> state = entry;
                default -> { }
            }
        }
        ObjectNode snapshot = mapper.createObjectNode();
        snapshot.put("taskId", runId);
        snapshot.put("sessionId", header.path("id").asString(""));
        snapshot.put("target", header.path("request").path("target").asString(""));
        snapshot.put("startedAt", header.path("timestamp").asString(""));
        snapshot.put("phase", phase);
        snapshot.set("events", events);
        snapshot.put("progress", events.isEmpty() ? "已记录" : events.get(events.size() - 1).path("message").asString("已记录"));
        if (state != null) {
            snapshot.put("status", state.path("status").asString("failed"));
            snapshot.put("finishedAt", state.path("finishedAt").asString(""));
            snapshot.put("modelCalls", state.path("modelCalls").asInt(modelCalls));
            snapshot.set("usage", state.path("usage").isObject() ? state.path("usage") : mapper.createObjectNode());
            snapshot.set("error", state.path("error").isObject() ? state.path("error") : null);
        } else {
            snapshot.put("status", "failed");
            snapshot.put("modelCalls", modelCalls);
            snapshot.set("usage", mapper.createObjectNode());
            ObjectNode error = mapper.createObjectNode();
            error.put("code", "RESEARCH_INTERRUPTED");
            error.put("message", "研究在完成前中断（服务重启或异常退出），以下是已记录的过程。");
            snapshot.set("error", error);
        }
        snapshot.set("report", report != null && report.isObject() ? report : null);
        snapshot.set("coverage", report != null && report.path("coverage").isArray() ? report.path("coverage") : mapper.createArrayNode());
        snapshot.set("sources", report != null && report.path("sources").isArray() ? report.path("sources") : mapper.createArrayNode());
        snapshot.set("toolCalls", report != null && report.path("toolCalls").isArray() ? report.path("toolCalls") : mapper.createArrayNode());
        snapshot.put("storage", "session_jsonl");
        return snapshot;
    }

    private ObjectNode summary(List<JsonNode> entries) {
        JsonNode header = entries.getFirst();
        ObjectNode summary = mapper.createObjectNode();
        summary.put("sessionId", header.path("id").asString(""));
        summary.put("runId", header.path("runId").asString(""));
        summary.put("createdAt", header.path("timestamp").asString(""));
        summary.put("target", header.path("request").path("target").asString(""));
        summary.put("question", header.path("request").path("question").asString(""));
        summary.put("status", "failed");
        for (JsonNode entry : entries) {
            String type = entry.path("type").asString("");
            if ("run_state".equals(type)) summary.put("status", entry.path("status").asString("failed"));
            if ("report".equals(type)) summary.put("title", entry.path("report").path("title").asString(""));
        }
        return summary;
    }

    private void indexFile(Path file) {
        String name = file.getFileName().toString();
        String sessionId = name.substring(0, name.length() - ".jsonl".length());
        if (!UUID_PATTERN.matcher(sessionId).matches()) return;
        try (Stream<String> lines = Files.lines(file, StandardCharsets.UTF_8)) {
            lines.map(this::parse).flatMap(Optional::stream)
                    .map(entry -> entry.path("runId").asString(""))
                    .filter(runId -> !runId.isEmpty())
                    .forEach(runId -> sessionByRun.put(runId, sessionId));
        } catch (IOException | UncheckedIOException error) {
            // 无法读取的文件不阻止启动；该会话不出现在记录中。
        }
    }

    private Set<String> readIds(Path file) {
        Set<String> ids = new HashSet<>();
        if (!Files.exists(file)) return ids;
        try (Stream<String> lines = Files.lines(file, StandardCharsets.UTF_8)) {
            lines.map(this::parse).flatMap(Optional::stream).forEach(entry -> ids.add(entry.path("id").asString("")));
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
        return ids;
    }

    /** 追加写入并刷到磁盘；若文件末尾是写到一半的残行，先补一个换行，让新行从干净的位置开始。 */
    private void write(Path file, String lines) {
        try {
            if (Files.exists(file) && Files.size(file) > 0) {
                // 追加模式的通道不能读，另开只读通道看最后一个字节。
                try (FileChannel reader = FileChannel.open(file, StandardOpenOption.READ)) {
                    ByteBuffer last = ByteBuffer.allocate(1);
                    reader.read(last, reader.size() - 1);
                    if (last.get(0) != '\n') lines = "\n" + lines;
                }
            }
        } catch (IOException error) {
            throw new UncheckedIOException("会话读取失败", error);
        }
        try (FileChannel channel = FileChannel.open(file, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
            ByteBuffer buffer = ByteBuffer.wrap(lines.getBytes(StandardCharsets.UTF_8));
            while (buffer.hasRemaining()) channel.write(buffer);
            channel.force(false);
        } catch (IOException error) {
            throw new UncheckedIOException("会话写入失败", error);
        }
    }

    private Optional<JsonNode> parse(String line) {
        if (line.isBlank()) return Optional.empty();
        try {
            JsonNode node = mapper.readTree(line);
            return node != null && node.isObject() ? Optional.of(node) : Optional.empty();
        } catch (RuntimeException error) {
            return Optional.empty();
        }
    }

    private Path file(String sessionId) {
        return directory.resolve(sessionId + ".jsonl");
    }

    private static void requireId(String id) {
        if (id == null || !UUID_PATTERN.matcher(id).matches()) throw new IllegalArgumentException("会话 id 无效");
    }
}
