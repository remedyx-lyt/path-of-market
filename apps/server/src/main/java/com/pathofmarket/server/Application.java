package com.pathofmarket.server;

import com.pathofmarket.server.config.AgentProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * Path of Market（市场之路）Java 主后端入口。
 */
@SpringBootApplication
@EnableConfigurationProperties(AgentProperties.class)
public class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
