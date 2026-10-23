package com.pathofmarket.server.controller;

import com.pathofmarket.server.client.AgentJobClient;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/research/jobs")
public class ResearchJobController {
    private final AgentJobClient client;
    public ResearchJobController(AgentJobClient client) { this.client = client; }
    @PostMapping public ResponseEntity<JsonNode> create(@RequestBody JsonNode input) { return client.create(input); }
    @GetMapping("/{taskId}") public ResponseEntity<JsonNode> get(@PathVariable UUID taskId) { return client.get(taskId); }
    @DeleteMapping("/{taskId}") public ResponseEntity<JsonNode> cancel(@PathVariable UUID taskId) { return client.cancel(taskId); }
}
