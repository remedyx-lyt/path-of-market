package com.pathofmarket.server.config;

import java.net.URI;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** Python 服务地址与有限等待时间，启动时检查配置。 */
@ConfigurationProperties(prefix = "agent")
public record AgentProperties(URI baseUrl, Duration connectTimeout, Duration requestTimeout) {

    public AgentProperties {
        if (baseUrl == null || baseUrl.getHost() == null
                || !("http".equals(baseUrl.getScheme()) || "https".equals(baseUrl.getScheme()))
                || baseUrl.getRawQuery() != null || baseUrl.getRawFragment() != null
                || baseUrl.getUserInfo() != null) {
            throw new IllegalArgumentException("agent.base-url 必须是没有查询参数、片段或用户信息的 HTTP(S) 服务地址");
        }
        requirePositiveMillis(connectTimeout, "agent.connect-timeout");
        requirePositiveMillis(requestTimeout, "agent.request-timeout");
    }

    private static void requirePositiveMillis(Duration timeout, String name) {
        if (timeout == null || timeout.compareTo(Duration.ofMillis(1)) < 0) {
            throw new IllegalArgumentException(name + " 必须至少为 1ms");
        }
    }

    public URI mockResearchUri() {
        return URI.create(baseUrl.toString().replaceAll("/+$", "") + "/research/mock");
    }
}
