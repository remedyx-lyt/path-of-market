package com.pathofmarket.server.controller;

import com.pathofmarket.server.client.AgentJobClient;
import com.pathofmarket.server.client.AgentServiceException;
import com.pathofmarket.server.session.SessionStore;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/research/jobs")
public class ResearchJobController {
    private final AgentJobClient client;
    private final SessionStore sessions;
    public ResearchJobController(AgentJobClient client, SessionStore sessions) { this.client = client; this.sessions = sessions; }
    @PostMapping public ResponseEntity<JsonNode> create(@RequestBody JsonNode input) { return client.create(input); }
    @PostMapping("/{taskId}/continue") public ResponseEntity<JsonNode> continueRun(@PathVariable UUID taskId) { return client.continueRun(taskId); }

    /** 先问 Python（运行中的任务在内存里）；找不到或 Python 不可用时，从会话 JSONL 还原已记录的研究。 */
    @GetMapping("/{taskId}") public ResponseEntity<JsonNode> get(@PathVariable UUID taskId) {
        try {
            return client.get(taskId);
        } catch (AgentServiceException error) {
            if (!Set.of("RESEARCH_NOT_FOUND", "AGENT_UNAVAILABLE").contains(error.code())) throw error;
            return sessions.snapshot(taskId.toString()).<ResponseEntity<JsonNode>>map(ResponseEntity::ok).orElseThrow(() -> error);
        }
    }
    @DeleteMapping("/{taskId}") public ResponseEntity<JsonNode> cancel(@PathVariable UUID taskId) { return client.cancel(taskId); }
}
