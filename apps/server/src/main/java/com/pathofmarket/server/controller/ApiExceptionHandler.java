package com.pathofmarket.server.controller;

import com.pathofmarket.server.client.AgentServiceException;
import com.pathofmarket.server.dto.ApiErrorResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** 为网页保留明确错误码；字段校验错误仍由 Python 返回 422 detail。 */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(AgentServiceException.class)
    public ResponseEntity<ApiErrorResponse> agentFailure(AgentServiceException exception) {
        return ResponseEntity.status(exception.status())
                .body(ApiErrorResponse.of(exception.code(), exception.getMessage()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiErrorResponse> invalidJson(HttpMessageNotReadableException exception) {
        return ResponseEntity.badRequest()
                .body(ApiErrorResponse.of("INVALID_JSON", "请求体必须包含有效的 JSON。"));
    }
}
