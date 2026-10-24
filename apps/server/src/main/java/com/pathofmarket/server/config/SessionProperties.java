package com.pathofmarket.server.config;

import java.nio.file.Path;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 研究会话 JSONL 的保存目录（默认项目根目录的 storage/sessions，不进 Git）。 */
@ConfigurationProperties(prefix = "sessions")
public record SessionProperties(String dir) {

    public SessionProperties {
        if (dir == null || dir.isBlank()) {
            throw new IllegalArgumentException("sessions.dir 不能为空");
        }
    }

    /** 按字符串读入再转换：Spring 把相对路径当资源路径处理时会规范化失败。相对路径以进程工作目录（apps/server）为起点。 */
    public Path path() {
        return Path.of(dir);
    }
}
