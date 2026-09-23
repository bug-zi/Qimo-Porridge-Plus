# core/ 引擎与基础设施域总文档

本文件夹放**用户不可见**的引擎与基础设施域，一域一文件夹。
域地图（代码锚点与文档状态）见 [`../project.md` §3.2](../project.md)。

每个域文件夹内固定两件套：`design.md` + `designs-specs.md`（README.md 登记的标准结构，
代替单独的文件夹总文档）。

modules/ 的功能域都会向下依赖这里的若干核心域（如几乎所有 AI 功能依赖 model-client，
所有长任务依赖 job-queue）；跨 core 域的调用关系优先看各域 designs-specs.md 的
"上游调用方/下游消费方"小节。
