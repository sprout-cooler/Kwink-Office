"""图片处理模块（v1.0.26）。

覆盖能力：格式转换 / 图片拼接 / 图片压缩 / 图片 OCR / 编辑（缩放旋转裁剪水印）。

**分层约定（各能力解耦、可独立调用）**：
    constants  格式白名单与参数边界（单一事实来源，前端能力清单由此生成）
    errors     ImageToolError 统一异常（能力文件不依赖 FastAPI）
    storage    按账号隔离的原子落盘
    imaging    Pillow 底层：安全解码 / 像素炸弹防护 / 色彩模式归一 / 编码
    convert    ① 格式转换（可单独 import 调用）
    stitch     ② 拼接
    compress   ③ 压缩
    transform  ④ 编辑
    ocr        ⑤ OCR（复用项目既有 VLM 通道，不新增依赖）
    service    编排 + 记录登记 + 归属校验
    router     HTTP 接口（唯一把 ImageToolError 翻译成 HTTP 的地方）

能力文件只 import 本包内的 constants/errors/imaging，**不碰数据库与身份**，
因此可以脱离 Web 框架直接在脚本里复用。
"""
