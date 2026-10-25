package com.pathofmarket.server.controller;

import com.pathofmarket.server.dto.ApiErrorResponse;
import com.pathofmarket.server.memory.ResearchMemoryStore;
import java.util.function.Supplier;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

/** 单用户记忆：网页查看/编辑，Python读取/提交带原话候选。都不直接调用模型。 */
@RestController
public class ResearchMemoryController {
    private final ResearchMemoryStore store;
    public ResearchMemoryController(ResearchMemoryStore store) { this.store = store; }

    @GetMapping({"/api/research/memory", "/internal/research/memory"})
    public ResponseEntity<?> get(@RequestParam(defaultValue = "") String query, @RequestParam(defaultValue = "20") int limit,
                                 @RequestParam(defaultValue = "") String excludeRoot) {
        return call(() -> {
            if (query.length() > 120) throw new IllegalArgumentException("检索词最多120字");
            if (!excludeRoot.isBlank()) java.util.UUID.fromString(excludeRoot);
            return store.snapshot(query, Math.max(1, Math.min(limit, 30)), excludeRoot);
        });
    }
    @PostMapping("/api/research/memory")
    public ResponseEntity<?> edit(@RequestBody JsonNode body) { return call(() -> store.edit(body)); }
    @PostMapping("/internal/research/memory/suggestions")
    public ResponseEntity<?> suggest(@RequestBody JsonNode body) { return call(() -> store.suggest(body)); }

    private ResponseEntity<?> call(Supplier<JsonNode> action) {
        try { return ResponseEntity.ok(action.get()); }
        catch (ResearchMemoryStore.Conflict error) { return ResponseEntity.status(409).body(ApiErrorResponse.of("MEMORY_CONFLICT", error.getMessage())); }
        catch (IllegalArgumentException error) { return ResponseEntity.badRequest().body(ApiErrorResponse.of("INVALID_MEMORY", error.getMessage())); }
        catch (ResearchMemoryStore.Unavailable error) { return ResponseEntity.status(503).body(ApiErrorResponse.of("MEMORY_UNAVAILABLE", error.getMessage())); }
    }
}
