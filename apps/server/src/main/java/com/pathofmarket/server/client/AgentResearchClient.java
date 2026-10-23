package com.pathofmarket.server.client;

import com.pathofmarket.server.config.AgentProperties;
import java.io.IOException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** 调用 Python；保留 JSON 类型，由 Python 统一校验研究字段。 */
@Component
public class AgentResearchClient {

    private static final Map<String, String> MODEL_ERRORS = Map.ofEntries(
            Map.entry("MODEL_NOT_CONFIGURED", "请在项目根目录 .env 填写模型密钥并保存。"),
            Map.entry("MODEL_CONFIG_ERROR", "模型配置无效，请检查 .env 的接口地址、模型名称和等待上限。"),
            Map.entry("MODEL_AUTH_FAILED", "模型密钥验证失败，请检查密钥和账户权限。"),
            Map.entry("MODEL_BALANCE_INSUFFICIENT", "模型账户余额或额度不足，请到供应商平台检查。"),
            Map.entry("MODEL_RATE_LIMITED", "模型调用过于频繁或额度受限，请稍后再试。"),
            Map.entry("MODEL_UPSTREAM_ERROR", "模型接口暂时无法完成请求，请检查模型配置或稍后重试。"),
            Map.entry("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。"),
            Map.entry("MODEL_UNAVAILABLE", "无法连接模型接口，请检查网络和接口地址。"),
            Map.entry("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的报告，请重试或调整输出长度。"));

    private final AgentProperties properties;
    private final JsonMapper jsonMapper;
    private final HttpClient httpClient;

    public AgentResearchClient(AgentProperties properties, JsonMapper jsonMapper) {
        this.properties = properties;
        this.jsonMapper = jsonMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    public ResponseEntity<JsonNode> researchMock(JsonNode input) {
        return research(input, properties.mockResearchUri(), properties.requestTimeout(), false);
    }

    public ResponseEntity<JsonNode> researchModel(JsonNode input) {
        return research(input, properties.modelResearchUri(), properties.modelRequestTimeout(), true);
    }

    private ResponseEntity<JsonNode> research(JsonNode input, URI uri, Duration timeout, boolean model) {
        var request = HttpRequest.newBuilder(uri)
                .timeout(timeout)
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(input.toString(), StandardCharsets.UTF_8))
                .build();

        var pending = httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        HttpResponse<String> response;
        try {
            // 等待完整响应，包括响应正文，避免只限制到响应头到达的时间。
            response = pending.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException exception) {
            pending.cancel(true);
            throw timeout();
        } catch (InterruptedException exception) {
            pending.cancel(true);
            Thread.currentThread().interrupt();
            throw unavailable();
        } catch (ExecutionException exception) {
            if (exception.getCause() instanceof HttpTimeoutException) {
                throw timeout();
            }
            if (exception.getCause() instanceof IOException) {
                throw unavailable();
            }
            throw new AgentServiceException(HttpStatus.BAD_GATEWAY, "AGENT_ERROR", "研究服务请求失败，请稍后重试。");
        }

        if (response.statusCode() != 200 && response.statusCode() != 422
                && !(model && (response.statusCode() == 502 || response.statusCode() == 503 || response.statusCode() == 504))) {
            throw new AgentServiceException(HttpStatus.BAD_GATEWAY, "AGENT_ERROR", "研究服务暂时无法完成请求，请稍后重试。");
        }

        JsonNode body;
        try {
            body = jsonMapper.readTree(response.body());
        } catch (JacksonException exception) {
            throw invalidResponse();
        }
        if (body == null || !body.isObject()) {
            throw invalidResponse();
        }

        if (model && response.statusCode() != 200 && response.statusCode() != 422) {
            String code = body.path("error").path("code").asString("");
            if (!MODEL_ERRORS.containsKey(code)) {
                throw invalidResponse();
            }
            // 仅转发已知错误码和本地文案，不透传上游正文、配置或密钥。
            throw new AgentServiceException(HttpStatus.valueOf(response.statusCode()), code, MODEL_ERRORS.get(code));
        }

        if (response.statusCode() == 422) {
            if (!body.path("detail").isArray() || body.path("detail").isEmpty()) {
                throw invalidResponse();
            }
            return ResponseEntity.unprocessableContent().body(body);
        }

        if (!(model ? isModelReport(body) : isMockReport(body))) {
            throw invalidResponse();
        }
        return ResponseEntity.ok(body);
    }

    private static boolean isModelReport(JsonNode body) {
        if (!"model".equals(body.path("mode").asString(""))
                || !body.path("isMock").isBoolean() || body.path("isMock").asBoolean()
                || !"not_retrieved".equals(body.path("evidenceStatus").asString(""))
                || !body.path("asOfDate").isString()
                || !"completed".equals(body.path("run").path("status").asString(""))
                || !body.path("run").path("taskId").isString()
                || !body.path("run").path("model").isString()
                || !body.path("limitations").isArray() || body.path("limitations").isEmpty()) {
            return false;
        }
        for (String field : new String[]{"target", "question", "userStyle", "title", "summary"}) {
            if (!body.path(field).isString()) { return false; }
        }
        if (!body.path("omens").isArray() || !body.path("sections").isArray() || body.path("sections").size() < 2
                || !body.path("sources").isArray() || !body.path("sources").isEmpty()
                || !body.path("toolCalls").isArray() || !body.path("toolCalls").isEmpty()) {
            return false;
        }
        for (JsonNode section : body.path("sections")) {
            if (!section.isObject() || !section.path("heading").isString() || !section.path("content").isString()) { return false; }
        }
        for (JsonNode limitation : body.path("limitations")) {
            if (!limitation.isString()) { return false; }
        }
        return true;
    }

    private static boolean isMockReport(JsonNode body) {
        if (!body.path("mode").isString() || !"mock".equals(body.path("mode").asString())
                || !body.path("isMock").isBoolean() || !body.path("isMock").asBoolean()) {
            return false;
        }
        for (String field : new String[]{"target", "question", "userStyle", "title", "summary"}) {
            if (!body.path(field).isString()) {
                return false;
            }
        }
        if (!body.path("omens").isArray() || !body.path("sections").isArray()
                || !body.path("sources").isArray() || !body.path("sources").isEmpty()
                || !body.path("toolCalls").isArray() || !body.path("toolCalls").isEmpty()) {
            return false;
        }
        for (JsonNode section : body.path("sections")) {
            if (!section.isObject() || !section.path("heading").isString() || !section.path("content").isString()) {
                return false;
            }
        }
        return true;
    }

    private static AgentServiceException timeout() {
        return new AgentServiceException(HttpStatus.GATEWAY_TIMEOUT, "AGENT_TIMEOUT", "研究服务响应超时，请稍后重试。");
    }

    private static AgentServiceException unavailable() {
        return new AgentServiceException(HttpStatus.SERVICE_UNAVAILABLE, "AGENT_UNAVAILABLE", "无法连接研究服务，请确认 Python 服务已启动。");
    }

    private static AgentServiceException invalidResponse() {
        return new AgentServiceException(HttpStatus.BAD_GATEWAY, "AGENT_INVALID_RESPONSE", "研究服务返回了无法识别的结果，请稍后重试。");
    }
}
