package com.pathofmarket.server.controller;

import com.pathofmarket.server.dto.ApiErrorResponse;
import com.pathofmarket.server.session.SessionStore;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

/**
 * 会话存储接口。
 * <ul>
 *   <li>{@code POST /internal/sessions/{id}/entries}：Python 研究服务提交条目（只在本机调用；网页代理只转发 /api，不会到达这里）。</li>
 *   <li>{@code GET /api/research/sessions}：网页的“最近研究”列表。</li>
 * </ul>
 */
@RestController
public class SessionController {
    private final SessionStore store;

    public SessionController(SessionStore store) { this.store = store; }

    @PostMapping("/internal/sessions/{sessionId}/entries")
    public ResponseEntity<?> append(@PathVariable String sessionId, @RequestBody JsonNode body) {
        JsonNode entries = body.path("entries");
        if (!entries.isArray() || entries.isEmpty() || entries.size() > 500) {
            return ResponseEntity.badRequest().body(ApiErrorResponse.of("INVALID_ENTRIES", "entries 须为 1 至 500 条的数组。"));
        }
        List<JsonNode> list = new ArrayList<>();
        entries.forEach(list::add);
        try {
            return ResponseEntity.ok(Map.of("written", store.append(sessionId, list), "received", list.size()));
        } catch (IllegalArgumentException error) {
            return ResponseEntity.badRequest().body(ApiErrorResponse.of("INVALID_ENTRIES", error.getMessage()));
        }
    }

    @GetMapping("/api/research/sessions")
    public Map<String, Object> recent(@RequestParam(defaultValue = "20") int limit) {
        return Map.of("sessions", store.recent(Math.max(1, Math.min(limit, 100))));
    }
}
