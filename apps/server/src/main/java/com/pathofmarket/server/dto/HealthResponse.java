package com.pathofmarket.server.dto;

/** 健康检查的返回格式。 */
public record HealthResponse(String status, String service) {
}
