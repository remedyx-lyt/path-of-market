package com.pathofmarket.server.controller;

import com.pathofmarket.server.dto.HealthResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** 确认 Java 主后端可以接收请求，不检查尚未接入的外部服务。 */
@RestController
public class HealthController {

    @GetMapping("/api/health")
    public HealthResponse health() {
        return new HealthResponse("ok", "server");
    }
}
