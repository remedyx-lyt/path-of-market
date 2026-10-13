package com.pathofmarket.server.client;

import com.pathofmarket.server.config.AgentProperties;
import java.io.IOException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
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
        var request = HttpRequest.newBuilder(properties.mockResearchUri())
                .timeout(properties.requestTimeout())
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(input.toString(), StandardCharsets.UTF_8))
                .build();

        var pending = httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        HttpResponse<String> response;
        try {
            // 等待完整响应，包括响应正文，避免只限制到响应头到达的时间。
            response = pending.get(properties.requestTimeout().toMillis(), TimeUnit.MILLISECONDS);
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

        if (response.statusCode() != 200 && response.statusCode() != 422) {
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

        if (response.statusCode() == 422) {
            if (!body.path("detail").isArray() || body.path("detail").isEmpty()) {
                throw invalidResponse();
            }
            return ResponseEntity.unprocessableContent().body(body);
        }

        if (!isMockReport(body)) {
            throw invalidResponse();
        }
        return ResponseEntity.ok(body);
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
