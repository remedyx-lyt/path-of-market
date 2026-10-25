package com.pathofmarket.server.memory;

import com.pathofmarket.server.config.SessionProperties;
import com.pathofmarket.server.session.SessionStore;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** 单用户跨会话记忆：用户确认的偏好 + 有用户原话的候选 + 可追溯研究经历。
 * 参考Claude Code可编辑持久记忆、OpenAI notes→consolidation和按需注入；不保存模型推断的财务事实。
 */
@Component
public class ResearchMemoryStore {
    private static final Set<String> CATEGORIES = Set.of("research_preference", "risk_focus", "watch_company");
    private static final Map<String, List<String>> THEMES = new LinkedHashMap<>();
    static {
        THEMES.put("现金流", List.of("现金流", "回款"));
        THEMES.put("资产负债", List.of("应收", "负债", "存货", "资产负债"));
        THEMES.put("业务与竞争", List.of("业务", "竞争", "客户", "行业"));
        THEMES.put("成长与研发", List.of("研发", "成长", "营收", "收入", "利润"));
        THEMES.put("风险", List.of("风险", "保守", "下行", "反方"));
        THEMES.put("股价与估值", List.of("股价", "行情", "估值", "回撤"));
    }
    private final Path file;
    private final SessionStore sessions;
    private final JsonMapper mapper;

    public ResearchMemoryStore(SessionProperties properties, SessionStore sessions, JsonMapper mapper) {
        this.file = properties.path().toAbsolutePath().normalize().resolve("memory/user.json");
        this.sessions = sessions;
        this.mapper = mapper;
    }

    public synchronized ObjectNode snapshot(String query, int limit) {
        return snapshot(query, limit, "");
    }

    public synchronized ObjectNode snapshot(String query, int limit, String excludeRoot) {
        ObjectNode state = read();
        ObjectNode result = state.deepCopy();
        ArrayNode notes = mapper.createArrayNode();
        for (JsonNode note : state.path("notes")) if (!"rejected".equals(note.path("status").asString(""))) notes.add(note);
        result.set("notes", notes);
        List<ObjectNode> history = sessions.memoryInputs();
        Set<String> ignored = strings(state.path("ignoredTargets"));
        history.removeIf(e -> ignored.contains(e.path("target").asString("")) || (!excludeRoot.isBlank() && excludeRoot.equals(e.path("rootTaskId").asString(""))));
        String search = query == null ? "" : query.strip().toLowerCase(Locale.ROOT);
        List<ObjectNode> matching = history.stream().filter(e -> search.isBlank()
                || (e.path("target").asString("") + " " + e.path("question").asString("")).toLowerCase(Locale.ROOT).contains(search)).toList();
        ArrayNode episodes = mapper.createArrayNode();
        matching.stream().limit(limit).forEach(episodes::add);
        result.set("episodes", episodes);
        result.put("totalEpisodes", history.size());
        result.put("matchedEpisodes", matching.size());
        Map<String, ObjectNode> companies = new LinkedHashMap<>();
        for (ObjectNode entry : history) {
            String target = entry.path("target").asString("");
            ObjectNode company = companies.computeIfAbsent(target, key -> {
                ObjectNode c = mapper.createObjectNode();
                c.put("target", key); c.put("researchCount", 0); c.put("followupCount", 0);
                c.put("lastSeen", entry.path("timestamp").asString(""));
                c.put("latestTaskId", entry.path("rootTaskId").asString(""));
                return c;
            });
            String count = "research".equals(entry.path("kind").asString("")) ? "researchCount" : "followupCount";
            company.put(count, company.path(count).asInt(0) + 1);
        }
        ArrayNode companyList = mapper.createArrayNode();
        companies.values().stream().filter(c -> search.isBlank() || c.path("target").asString("").toLowerCase(Locale.ROOT).contains(search))
                .limit(30).forEach(companyList::add);
        result.set("companies", companyList);
        result.put("companyCount", companies.size());
        ArrayNode themes = mapper.createArrayNode();
        // 只计最近30次成功任务/追问；含默认模板，所以这些是任务主题观察，不是已确认的永久偏好。
        for (var theme : THEMES.entrySet()) {
            List<ObjectNode> hits = history.stream().limit(30).filter(e -> theme.getValue().stream()
                    .anyMatch(word -> e.path("question").asString("").contains(word))).toList();
            if (hits.isEmpty()) continue;
            ObjectNode t = mapper.createObjectNode(); t.put("name", theme.getKey()); t.put("count", hits.size());
            ArrayNode evidence = mapper.createArrayNode(); hits.stream().limit(3).forEach(evidence::add);
            t.set("evidence", evidence); themes.add(t);
        }
        result.set("themes", themes);
        result.put("observationScope", "最近30次成功研究/追问的任务主题（包含默认问题）；仅表示研究涉及，不据此判断持仓、风险承受力或长期偏好。");
        return result;
    }

    public synchronized ObjectNode edit(JsonNode body) {
        ObjectNode state = read();
        if (!body.path("revision").isIntegralNumber() || body.path("revision").asLong(-1) != state.path("revision").asLong(0))
            throw new Conflict("记忆已更新，请刷新后再保存，避免覆盖另一处修改。");
        String action = text(body, "action", 30);
        ArrayNode notes = (ArrayNode) state.path("notes");
        switch (action) {
            case "toggle" -> {
                if (!body.path("enabled").isBoolean()) throw new IllegalArgumentException("enabled须为布尔值");
                state.put("enabled", body.path("enabled").asBoolean());
            }
            case "save" -> {
                String id = body.path("id").asString("");
                ObjectNode existing = id.isBlank() ? null : find(notes, id);
                String content = text(body, "text", 500), category = category(body);
                if (existing == null && activeCount(notes) >= 48) throw new IllegalArgumentException("最多保留48条偏好与候选，请先整理旧记忆。");
                ObjectNode note = existing == null ? mapper.createObjectNode() : existing;
                if (existing == null) { note.put("id", UUID.randomUUID().toString()); notes.add(note); }
                note.put("text", content); note.put("category", category); note.put("status", "confirmed");
                note.put("updatedAt", Instant.now().toString());
                note.put("confirmedBy", "local_user");
            }
            case "forget" -> {
                ObjectNode note = find(notes, text(body, "id", 80));
                // 保留内容指纹防止同一候选再次出现；正文和原话从记忆文件移除，原研究会话独立保留。
                String fingerprint = fingerprint(note.path("text").asString(""));
                note.removeAll(); note.put("id", text(body, "id", 80)); note.put("status", "rejected");
                note.put("fingerprint", fingerprint);
            }
            case "ignore_company", "restore_company" -> {
                String target = text(body, "target", 120);
                Set<String> ignored = strings(state.path("ignoredTargets"));
                if (action.equals("ignore_company")) ignored.add(target); else ignored.remove(target);
                if (ignored.size() > 100) throw new IllegalArgumentException("忽略列表最多100个对象");
                ArrayNode ignoredList = mapper.createArrayNode(); ignored.forEach(ignoredList::add); state.set("ignoredTargets", ignoredList);
            }
            default -> throw new IllegalArgumentException("未知记忆操作");
        }
        write(state);
        return snapshot("", 20);
    }

    public synchronized ObjectNode suggest(JsonNode body) {
        ObjectNode state = read();
        if (!state.path("enabled").asBoolean(true)) throw new Conflict("研究记忆已关闭，未保存建议。");
        String runId = text(body, "runId", 80); UUID.fromString(runId);
        String content = text(body, "text", 500), quote = text(body, "quote", 500), category = category(body);
        String source = sessions.memorySource(runId).orElseThrow(() -> new IllegalArgumentException("找不到当前运行的真实用户输入"));
        if (!source.contains(quote)) throw new IllegalArgumentException("quote须逐字出现在本次用户问题或研究风格中，不能来自报告/模型回复。");
        ArrayNode notes = (ArrayNode) state.path("notes");
        for (JsonNode note : notes) if (fingerprint(content).equals(note.path("fingerprint").asString(""))
                || content.equals(note.path("text").asString(""))) {
            ObjectNode result = mapper.createObjectNode(); result.put("status", "already_recorded"); return result;
        }
        if (activeCount(notes) >= 48) throw new IllegalArgumentException("记忆候选已满，请先整理旧记忆。");
        ObjectNode note = mapper.createObjectNode();
        note.put("id", UUID.randomUUID().toString()); note.put("text", content); note.put("category", category);
        note.put("status", "suggested"); note.put("runId", runId); note.put("quote", quote);
        note.put("updatedAt", Instant.now().toString()); notes.add(note);
        write(state);
        ObjectNode result = mapper.createObjectNode(); result.put("status", "suggested"); result.set("note", note);
        return result;
    }

    private ObjectNode read() {
        if (!Files.exists(file)) {
            ObjectNode state = mapper.createObjectNode(); state.put("schemaVersion", 1); state.put("revision", 0);
            state.put("enabled", true); state.set("notes", mapper.createArrayNode()); state.set("ignoredTargets", mapper.createArrayNode()); return state;
        }
        try {
            JsonNode state = mapper.readTree(Files.readString(file, StandardCharsets.UTF_8));
            if (state == null || !state.isObject() || state.path("schemaVersion").asInt(0) != 1
                    || !state.path("notes").isArray() || !state.path("ignoredTargets").isArray()
                    || !state.path("enabled").isBoolean() || !state.path("revision").isIntegralNumber() || state.path("revision").asLong(-1) < 0)
                throw new IOException("记忆文件结构无效，原文件保留");
            return (ObjectNode) state;
        } catch (IOException | RuntimeException error) { throw new Unavailable("记忆文件暂不可读，原文件保留。", error); }
    }

    private void write(ObjectNode state) {
        ArrayNode trimmed = mapper.createArrayNode();
        List<JsonNode> rejected = new ArrayList<>();
        for (JsonNode note : state.path("notes")) {
            if ("rejected".equals(note.path("status").asString(""))) rejected.add(note); else trimmed.add(note);
        }
        rejected.stream().skip(Math.max(0, rejected.size() - 256)).forEach(trimmed::add);
        state.set("notes", trimmed);
        state.put("revision", state.path("revision").asLong(0) + 1); state.put("updatedAt", Instant.now().toString());
        Path temp = null;
        try {
            Files.createDirectories(file.getParent()); temp = Files.createTempFile(file.getParent(), "user-", ".tmp");
            try (FileChannel channel = FileChannel.open(temp, StandardOpenOption.WRITE)) {
                ByteBuffer buffer = ByteBuffer.wrap(mapper.writeValueAsString(state).getBytes(StandardCharsets.UTF_8));
                while (buffer.hasRemaining()) channel.write(buffer); channel.force(true);
            }
            try { Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException error) { Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING); }
        } catch (IOException error) { throw new Unavailable("记忆保存失败，原文件保留。", error); }
        finally { if (temp != null) try { Files.deleteIfExists(temp); } catch (IOException ignored) { } }
    }

    private String category(JsonNode body) {
        String value = text(body, "category", 30);
        if (!CATEGORIES.contains(value)) throw new IllegalArgumentException("category无效"); return value;
    }
    private String text(JsonNode body, String key, int max) {
        if (!body.path(key).isString()) throw new IllegalArgumentException(key + "须为文字");
        String value = body.path(key).asString("").strip();
        if (value.isBlank() || value.length() > max) throw new IllegalArgumentException(key + "长度应为1至" + max); return value;
    }
    private Set<String> strings(JsonNode list) { Set<String> values = new LinkedHashSet<>(); list.forEach(v -> values.add(v.asString(""))); return values; }
    private ObjectNode find(ArrayNode notes, String id) {
        for (JsonNode note : notes) if (id.equals(note.path("id").asString("")) && !"rejected".equals(note.path("status").asString(""))) return (ObjectNode) note;
        throw new IllegalArgumentException("记忆条目不存在或已移除");
    }
    private long activeCount(ArrayNode notes) { long count = 0; for (JsonNode n : notes) if (!"rejected".equals(n.path("status").asString(""))) count++; return count; }
    private String fingerprint(String value) { return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8)).toString(); }
    public static class Conflict extends RuntimeException { public Conflict(String message) { super(message); } }
    public static class Unavailable extends RuntimeException { public Unavailable(String message, Throwable cause) { super(message, cause); } }
}
