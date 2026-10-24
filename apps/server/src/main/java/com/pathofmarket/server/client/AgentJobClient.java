package com.pathofmarket.server.client;

import com.pathofmarket.server.config.AgentProperties;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeoutException;
import java.net.http.HttpTimeoutException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** 短请求启动/读取/取消长任务；报告仍经 Java 返回，浏览器不直连 Python。 */
@Component
public class AgentJobClient {
    private final AgentProperties properties;
    private final JsonMapper mapper;
    private final HttpClient client;
    private static final Set<String> STATES = Set.of("queued", "running", "completed", "partial", "failed", "cancelled");
    private static final Set<String> ERRORS = Set.of("MODEL_NOT_CONFIGURED", "MODEL_CONFIG_ERROR", "MODEL_AUTH_FAILED",
            "MODEL_BALANCE_INSUFFICIENT", "MODEL_RATE_LIMITED", "MODEL_UPSTREAM_ERROR", "MODEL_TIMEOUT",
            "MODEL_UNAVAILABLE", "MODEL_INVALID_RESPONSE", "RESEARCH_BUSY", "RESEARCH_NOT_FOUND", "RESEARCH_FAILED", "RESEARCH_NOT_RESUMABLE");

    public AgentJobClient(AgentProperties properties, JsonMapper mapper) {
        this.properties = properties;
        this.mapper = mapper;
        this.client = HttpClient.newBuilder().connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    public ResponseEntity<JsonNode> create(JsonNode body) { return request("POST", "", body); }
    public ResponseEntity<JsonNode> get(UUID taskId) { return request("GET", "/" + taskId, null); }
    public ResponseEntity<JsonNode> cancel(UUID taskId) { return request("DELETE", "/" + taskId, null); }
    public ResponseEntity<JsonNode> continueRun(UUID taskId) { return request("POST", "/" + taskId + "/continue", null); }
    public ResponseEntity<JsonNode> chat(UUID taskId, JsonNode body) { return request("POST", "/" + taskId + "/chat", body); }

    private ResponseEntity<JsonNode> request(String method, String suffix, JsonNode body) {
        URI uri = URI.create(properties.baseUrl().toString().replaceAll("/+$", "") + "/research/jobs" + suffix);
        Duration timeout = properties.requestTimeout().compareTo(Duration.ofSeconds(15)) < 0
                ? properties.requestTimeout() : Duration.ofSeconds(15);
        var builder = HttpRequest.newBuilder(uri).timeout(timeout)
                .header("Accept", "application/json").header("Content-Type", "application/json; charset=utf-8");
        builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofString(body.toString(), StandardCharsets.UTF_8));
        var pending = client.sendAsync(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        HttpResponse<String> response;
        try {
            response = pending.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException error) {
            pending.cancel(true);
            throw failure(HttpStatus.GATEWAY_TIMEOUT, "AGENT_TIMEOUT", "研究任务接口响应超时。");
        } catch (InterruptedException error) {
            pending.cancel(true); Thread.currentThread().interrupt();
            throw failure(HttpStatus.SERVICE_UNAVAILABLE, "AGENT_UNAVAILABLE", "研究服务连接被中断。");
        } catch (ExecutionException error) {
            pending.cancel(true);
            if (error.getCause() instanceof HttpTimeoutException)
                throw failure(HttpStatus.GATEWAY_TIMEOUT, "AGENT_TIMEOUT", "研究任务接口响应超时。");
            throw failure(HttpStatus.SERVICE_UNAVAILABLE, "AGENT_UNAVAILABLE", "无法读取研究任务，请检查 Python 服务。");
        }
        JsonNode result;
        try { result = mapper.readTree(response.body()); }
        catch (Exception error) { throw invalid(); }
        if (result == null || !result.isObject()) throw invalid();
        int status = response.statusCode();
        if (status == 422 && result.path("detail").isArray() && !result.path("detail").isEmpty())
            return ResponseEntity.unprocessableContent().body(result);
        if (status != 200 && status != 202) {
            String code = result.path("error").path("code").asString("");
            if (!ERRORS.contains(code) || !Set.of(404, 409, 502, 503, 504).contains(status)) throw invalid();
            String message = switch (code) {
                case "RESEARCH_BUSY" -> "已有研究正在运行，请等待完成或先停止该任务。";
                case "RESEARCH_NOT_FOUND" -> "任务不存在或研究服务已重启，请重新开始。";
                case "RESEARCH_NOT_RESUMABLE" -> "此任务暂时无法接续，请检查原任务状态、模型配置与会话记录。";
                case "MODEL_NOT_CONFIGURED" -> "请在根目录 .env 中填写模型密钥并保存。";
                case "MODEL_CONFIG_ERROR" -> "模型配置无效，请检查本地配置。";
                default -> "研究任务暂时无法执行，请检查模型账户或稍后重试。";
            };
            throw failure(HttpStatus.valueOf(status), code, message);
        }
        validateJob(result);
        if (suffix.endsWith("/continue") || suffix.endsWith("/chat")) {
            String action = suffix.endsWith("/chat") ? "/chat" : "/continue";
            if (!suffix.equals("/" + result.path("parentTaskId").asString("") + action)) throw invalid();
        } else if (!suffix.isEmpty() && !suffix.equals("/" + result.path("taskId").asString(""))) throw invalid();
        return ResponseEntity.status(status).body(result);
    }

    private static void validateJob(JsonNode result) {
        try { UUID.fromString(result.path("taskId").asString("")); }
        catch (IllegalArgumentException error) { throw invalid(); }
        if (!STATES.contains(result.path("status").asString("")) || !result.path("progress").isString()
                || !result.path("events").isArray() || !result.path("toolCalls").isArray()
                || !result.path("coverage").isArray() || !result.path("sources").isArray()) throw invalid();
        JsonNode report = result.path("report");
        if (!report.isMissingNode() && !report.isNull()) {
            if (!"agent".equals(report.path("mode").asString("")) || !report.path("isMock").isBoolean()
                    || report.path("isMock").asBoolean() || !report.path("sections").isArray()
                    || !report.path("sources").isArray() || !report.path("coverage").isArray()
                    || !report.path("title").isString() || !report.path("summary").isString()) throw invalid();
            for (JsonNode section : report.path("sections")) {
                if (!section.path("heading").isString() || !section.path("content").isString()
                        || !section.path("citations").isArray()) throw invalid();
            }
            for (JsonNode source : report.path("sources")) {
                if (!source.path("sourceId").isString() || !source.path("title").isString()
                        || !source.path("url").asString("").startsWith("https://")) throw invalid();
            }
        }
    }

    private static AgentServiceException invalid() {
        return failure(HttpStatus.BAD_GATEWAY, "AGENT_INVALID_RESPONSE", "研究任务返回的结构无效。");
    }
    private static AgentServiceException failure(HttpStatus status, String code, String message) {
        return new AgentServiceException(status, code, message);
    }
}
