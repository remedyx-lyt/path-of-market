package com.pathofmarket.server.controller;

import com.pathofmarket.server.client.AgentResearchClient;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** 主 API 入口，研究任务交给 Python 执行。 */
@RestController
public class ResearchController {

    private final AgentResearchClient agentResearchClient;

    public ResearchController(AgentResearchClient agentResearchClient) {
        this.agentResearchClient = agentResearchClient;
    }

    @PostMapping(value = "/api/research/mock", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<JsonNode> researchMock(@RequestBody JsonNode input) {
        return agentResearchClient.researchMock(input);
    }

    @PostMapping(value = "/api/research/model", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<JsonNode> researchModel(@RequestBody JsonNode input) {
        return agentResearchClient.researchModel(input);
    }
}
