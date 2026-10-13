package com.pathofmarket.server.client;

import org.springframework.http.HttpStatus;

/** 外部研究服务失败，不将其内部错误内容直接交给网页。 */
public class AgentServiceException extends RuntimeException {

    private final HttpStatus status;
    private final String code;

    public AgentServiceException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public HttpStatus status() {
        return status;
    }

    public String code() {
        return code;
    }
}
