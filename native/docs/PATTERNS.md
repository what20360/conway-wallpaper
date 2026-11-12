# 预设布局与 Life Lexicon 来源

008–024 的组合由本程序在 256×180 网格上生成，左右镜像且间距均匀。
010–018、020–024 同时上下镜像；008／009／019 的飞行器保持同向下落，不能为追求上下像素镜像而把一半改为向上飞行。
组合在 B3/S23 环绕网格上演化，不修改规则。阵列不是对单个细胞做放大，仍以一个物理细胞对应一个生命游戏细胞。

## 连续流星雨

- 008 为四列，列间距 60 格；009 为六列，列间距 40 格，均关于网格中轴对称。
- 每列每 9 行重复一艘向下 LWSS，上下边界同样保持该周期，没有旧版成组之间的大空档。
- 9 行是能整除 180、且保持这些飞行器独立运行的最小行周期；5／6 行周期会使相邻飞行器反应。不能把“连续”理解为无空细胞地贴在一起，否则不再是独立飞行器雨。
- 整个 008／009 每四代向下移动两格，可持续环绕。019 在竖列之间加入对称的脉冲星。
- 其他对称飞船、喷射器组合可能在环绕后相遇并演变；不承诺永不碰撞或永不消亡。

## 从词典选入的基础图案

参考用户提供的 [Life Lexicon](https://playgameoflife.com/lexicon)，提取各条目的第一幅细胞图，保存在 `conway_desktop/lexicon-patterns.json`，离线即可使用。保留原始相位，不将条目文字混入图案数据。

| 槽位 | 组合 | 基础图尺寸 | 组合方式 | 来源 |
| --- | --- | --- | --- | --- |
| 020 | Schick 引擎阵列 | 18×9 | 4×4 镜像阵列 | [Schick engine](https://playgameoflife.com/lexicon/Schick_engine) |
| 021 | Weekender 舰队 | 16×11 | 4×4 镜像阵列 | [Weekender](https://playgameoflife.com/lexicon/weekender) |
| 022 | 双蜂穿梭阵列 | 27×17 | 4×4 镜像阵列 | [Twin bees shuttle](https://playgameoflife.com/lexicon/twin_bees_shuttle) |
| 023 | 十五周期振荡器阵列 | 10×3 | 8×6 镜像阵列 | [Pentadecathlon](https://playgameoflife.com/lexicon/pentadecathlon) |
| 024 | Puffer 喷射器阵列 | 27×7 | 4×4 镜像阵列 | [Puffer](https://playgameoflife.com/lexicon/puffer) |

已用实际演化验证：Schick 基础图 12 代水平位移 6 格；Weekender 7 代竖直位移 2 格；双蜂穿梭 46 周期和十五周期振荡器 15 周期。022／023 整个阵列也保持相应周期。

原始图案与整理后的图案数据、镜像阵列数据遵循 **CC BY-SA 3.0**；归属 Life Lexicon 编者 **Stephen A. Silver** 及该词典所列各图案贡献者，网站由 Edwin Martin 维护。改动包括提取细胞行、镜像、平移和排列组合。具体各条目来源保存在 JSON 中。

许可：https://creativecommons.org/licenses/by-sa/3.0/

以上许可适用于图案数据；本项目独立编写的应用与排列生成代码沿用项目的软件许可。用户自己的预设不因导入此图案集而被改写。
