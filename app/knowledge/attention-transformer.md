---
id: attention-transformer
title: 注意力机制与 Transformer
title_en: Attention & Transformer
difficulty: 进阶
tags: [注意力机制, Transformer, 自注意力, 多头注意力, 序列建模]
---

# 注意力机制与 Transformer Attention & Transformer

## 一、概念与直觉

注意力机制(Attention)是一种让模型在处理某个元素时,动态地从一组上下文元素中"按相关性加权汇聚"信息的方法。一句话定义:给定一个查询(query),用它与一组键(key)计算相似度,再用相似度对相应的值(value)做加权平均,得到这个查询的上下文表示。

打个比方:你在图书馆找一本书的资料(query),书架上每本书都有书脊标签(key)和内容(value)。你不会平均地翻每本书,而是先看哪些标签和你的问题最匹配,匹配度高的多读,匹配度低的略读。注意力机制就是把"匹配度"变成可微的权重,让模型自动学会"该多看哪里"。

Transformer 是 2017 年提出(Vaswani 等《Attention Is All You Need》)的一种完全基于注意力、抛弃了循环(RNN)与卷积(CNN)的序列建模架构。它用自注意力(self-attention)让序列中每个位置都能直接与任意其他位置交互,因此可以高度并行,并能捕捉长距离依赖。它是 BERT、GPT 等现代大模型的共同基础。

## 二、核心知识点

1. 注意力的三要素是 Query、Key、Value(Q、K、V),通常由输入经过不同的线性变换得到。
2. 缩放点积注意力(Scaled Dot-Product Attention)用 Q 与 K 的点积衡量相关性,除以 $\sqrt{d_k}$ 缩放后做 softmax。
3. 自注意力指 Q、K、V 都来自同一个序列;它让每个位置都能"看到"整个序列。
4. 多头注意力(Multi-Head Attention)把表示拆成多个子空间并行做注意力,再拼接,使模型能关注不同类型的关系。
5. 由于注意力对位置不敏感(置换等变),Transformer 需额外加入位置编码(Positional Encoding)注入顺序信息。
6. Transformer 由 Encoder 和 Decoder 堆叠而成;每个子层都配有残差连接(Residual)和层归一化(LayerNorm)。
7. 每层还包含一个逐位置的前馈网络(Position-wise FFN),通常是两层带激活的全连接。
8. Decoder 使用掩码自注意力(masked self-attention)防止预测时看到未来位置,保证自回归性质。
9. 自注意力的时间与空间复杂度关于序列长度 $n$ 为 $O(n^2)$,这是长序列的主要瓶颈。
10. 相比 RNN,Transformer 的路径长度为常数 $O(1)$,更易学习长距离依赖且训练可并行。

## 三、关键公式 / 原理

缩放点积注意力的核心公式:

$\text{Attention}(Q,K,V) = \text{softmax}\left(\dfrac{QK^\top}{\sqrt{d_k}}\right)V$

符号含义:
- $Q \in \mathbb{R}^{n\times d_k}$:查询矩阵,$n$ 个查询,每个维度 $d_k$。
- $K \in \mathbb{R}^{m\times d_k}$:键矩阵,$m$ 个键。
- $V \in \mathbb{R}^{m\times d_v}$:值矩阵,与键一一对应。
- $QK^\top \in \mathbb{R}^{n\times m}$:每个查询与每个键的点积,即相关性打分。
- $\sqrt{d_k}$:缩放因子,防止维度大时点积过大导致 softmax 梯度消失。
- softmax 按行归一化,得到权重;再乘 $V$ 完成加权汇聚。

多头注意力:

$\text{head}_i = \text{Attention}(QW_i^Q, KW_i^K, VW_i^V)$
$\text{MultiHead}(Q,K,V) = \text{Concat}(\text{head}_1,\dots,\text{head}_h)W^O$

其中 $W_i^Q, W_i^K, W_i^V$ 是第 $i$ 个头的投影矩阵,$W^O$ 是输出投影。每个头维度通常取 $d_k=d_v=d_{\text{model}}/h$,使总计算量与单头相当。

位置编码(正弦版本):$PE_{(pos,2i)}=\sin(pos/10000^{2i/d})$,$PE_{(pos,2i+1)}=\cos(pos/10000^{2i/d})$。

## 四、典型例子 / 推导

设 $d_k=2$,序列长度为 2。给定:

- $Q = \begin{bmatrix}1 & 0\end{bmatrix}$(只算第一个查询)
- $K = \begin{bmatrix}1 & 0\\ 0 & 1\end{bmatrix}$,$V = \begin{bmatrix}10 & 0\\ 0 & 10\end{bmatrix}$

第一步,点积打分:$QK^\top = [\,1\cdot1+0\cdot0,\ \ 1\cdot0+0\cdot1\,] = [1,\ 0]$。

第二步,缩放:除以 $\sqrt{d_k}=\sqrt{2}\approx1.414$,得 $[0.707,\ 0]$。

第三步,softmax:$e^{0.707}\approx2.028$,$e^{0}=1$,和为 $3.028$,
权重 $=[2.028/3.028,\ 1/3.028]=[0.670,\ 0.330]$。

第四步,加权 $V$:
- 第一维:$0.670\times10 + 0.330\times0 = 6.70$
- 第二维:$0.670\times0 + 0.330\times10 = 3.30$

输出 $\approx[6.70,\ 3.30]$。

可见查询与第一个键更相关(点积更大),所以输出更偏向第一个值;但因为 softmax 是软性的,第二个值仍贡献了约三分之一。这正是注意力"软选择"的含义。

## 五、常见误区

1. "注意力权重就是模型的解释/重要性"。注意力权重只反映汇聚方式,与因果重要性不等价,不能直接当作可靠解释。
2. 混淆缩放因子。除的是 $\sqrt{d_k}$(键的维度的平方根),不是 $d_k$,也不是序列长度。
3. 以为多头注意力增加了总计算量。常见设计令每头维度为 $d_{\text{model}}/h$,总量与单头大致相同,关键是表达更丰富的子空间。
4. 忽略位置编码。自注意力本身对输入顺序不敏感,不加位置信息会把"我打你"和"你打我"看成相同集合。
5. 把 Encoder 的自注意力和 Decoder 的掩码自注意力混为一谈。Decoder 必须用下三角掩码,屏蔽未来位置以保持自回归。
6. 以为 Transformer 没有非线性序列建模能力就只靠注意力。真正的非线性主要来自逐位置 FFN 与激活函数,注意力本身在给定权重后是线性加权。

## 六、与其他知识点的联系

前置知识:线性代数(矩阵乘法、向量内积、softmax)、神经网络基础(全连接层、反向传播)、词嵌入(word embedding),以及序列模型 RNN/LSTM(理解 Transformer 为何要替代它们)。理解 softmax 与点积相似度是入门关键。

横向联系:注意力最早作为 RNN 编码器-解码器(seq2seq)的对齐机制提出(Bahdanau 2014),Transformer 将其推广为架构主干。LayerNorm、残差连接来自更通用的深度网络训练技巧。

后续延伸:基于 Transformer 的预训练模型(BERT 的掩码语言模型、GPT 的自回归语言模型);针对 $O(n^2)$ 复杂度的高效注意力(稀疏注意力、线性注意力、FlashAttention);跨模态应用(Vision Transformer、多模态大模型)。掌握本主题是理解大语言模型(LLM)的必经之路。

## 七、自测题(含参考答案)

1.(选择)缩放点积注意力中,点积要除以哪个量?
A. $d_k$  B. $\sqrt{d_k}$  C. 序列长度 $n$  D. $\sqrt{n}$
参考答案:B。解析:除以 $\sqrt{d_k}$ 是为了抵消高维点积方差随维度线性增长,避免 softmax 进入梯度极小的饱和区。

2.(判断)Transformer 不需要位置编码,因为自注意力天然能感知词序。
参考答案:错。解析:自注意力对输入是置换等变的,本身不含顺序信息,必须显式注入位置编码(或相对位置等机制)。

3.(简答)简述多头注意力相比单头注意力的优势。
参考答案:多头将表示投影到多个子空间并行计算注意力,使模型能同时关注不同类型的依赖关系(如句法、语义、远近),拼接后表达能力更强;在每头维度取 $d_{\text{model}}/h$ 时计算量与单头相近。

4.(计算)$Q=[0,1]$,$K=\begin{bmatrix}1&0\\0&1\end{bmatrix}$,$d_k=2$,求 softmax 前的缩放打分。
参考答案:$QK^\top=[0,1]$,除以 $\sqrt{2}\approx1.414$ 得 $[0,\ 0.707]$。解析:第二个键与查询点积更大,softmax 后第二个值将获得更高权重。
