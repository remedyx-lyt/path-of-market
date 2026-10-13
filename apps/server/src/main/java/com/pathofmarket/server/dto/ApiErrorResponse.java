package com.pathofmarket.server.dto;

/** 供网页识别和展示的稳定错误格式。 */
public record ApiErrorResponse(ErrorInfo error) {

    public record ErrorInfo(String code, String message) {
    }

    public static ApiErrorResponse of(String code, String message) {
        return new ApiErrorResponse(new ErrorInfo(code, message));
    }
}
