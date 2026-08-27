from __future__ import annotations

from .checkpoint_contracts import FORMULA_OUTPUT_CONTRACT_VERSION


# STRUCTURED_FORMULA_OUTPUT_RULES 和 with_structured_formula_rules() 给所有涉及公式的模型 Prompt 追加统一 KaTeX/JSON 输出约束。
STRUCTURED_FORMULA_OUTPUT_RULES = r"""
【统一公式输出规范（适用于所有课程）】
1. 仅对数学、统计、化学、工程等公式表达使用 KaTeX 兼容的 LaTeX；程序代码、Excel 公式、URL、文件路径和普通缩写保持原文。
2. JSON 中除 formula.expression 外，用户可见文本里的每个行内公式都用 \(...\) 完整包裹；formula.expression 只写公式本体，不加定界符。返回合法 JSON 时，LaTeX 反斜杠必须按 JSON 规则转义。
3. 上标写作 x^{2}，下标写作 v_{0}，同时有上下标写作 a_{n}^{2}；分式写作 \frac{a}{b}，复合分式必须完整分组，如 \frac{x}{1+\frac{a}{b}}；根式、向量、求和、积分和希腊字母分别使用 \sqrt{x}、\vec{v}、\sum、\int、\omega 等标准命令。
4. 最终展示内容不得把数学表达写成 10^3、v_0、i_c、1/3 或裸露的 \frac、\omega 等命令；单位 km/h、m/s，日期、路径和代码中的斜杠不改成分式。
5. 返回前检查公式定界符、花括号和命令是否成对完整，确保每段公式可由 KaTeX 独立渲染。
""".strip()


def with_structured_formula_rules(prompt: str) -> str:
    return f"{prompt.strip()}\n\n{STRUCTURED_FORMULA_OUTPUT_RULES}"
