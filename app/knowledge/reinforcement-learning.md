---
id: reinforcement-learning
title: 强化学习基础
title_en: Reinforcement Learning Basics
difficulty: 进阶
tags: [强化学习, 马尔可夫决策过程, 价值函数, 贝尔曼方程, 时序差分]
---

# 强化学习基础 Reinforcement Learning Basics

## 一、概念与直觉

强化学习(Reinforcement Learning, RL)研究的是:一个 **agent(智能体)** 在与 **environment(环境)** 的交互中,通过试错(trial and error)学习一套 **policy(策略)**,使其获得的长期累积奖励最大化。它既不同于监督学习(没有带标签的"正确答案"),也不同于无监督学习(目标不是发现数据结构),而是从延迟、稀疏的 **reward(奖励)** 信号中学习"该怎么做"。

可以用训练小狗作类比:你不会告诉狗每一步该如何抬腿(没有逐步标签),而是在它完成动作后给予零食或斥责(奖励信号)。狗需要自己摸索哪一连串动作能换来零食。这里的关键困难在于 **delayed reward(延迟奖励)** 与 **credit assignment(信用分配)**:奖励往往在很多步之后才出现,智能体必须判断是早先哪个动作真正起了作用。

强化学习还有一个独有的张力——**exploration vs. exploitation(探索与利用)**:既要利用已知能带来高奖励的动作,又要探索尚未尝试、可能更优的动作。如何平衡两者,是 RL 区别于其他学习范式的核心问题之一。

## 二、核心知识点

1. **MDP(Markov Decision Process,马尔可夫决策过程)** 是 RL 的数学框架,用五元组 $(S, A, P, R, \gamma)$ 描述:状态集、动作集、转移概率、奖励函数、折扣因子。
2. **Markov property(马尔可夫性)**:下一状态只依赖当前状态和动作,与历史无关,即 $P(s_{t+1}\mid s_t, a_t) = P(s_{t+1}\mid s_t,a_t,\dots,s_0,a_0)$。
3. **Policy(策略)** $\pi(a\mid s)$ 是从状态到动作(分布)的映射,分为确定性策略与随机策略。
4. **Return(回报)** $G_t$ 是从时刻 $t$ 起的折扣累积奖励;$\gamma\in[0,1]$ 控制对未来奖励的重视程度。
5. **State-value function(状态价值函数)** $V^\pi(s)$ 与 **action-value function(动作价值函数)** $Q^\pi(s,a)$ 分别衡量在策略 $\pi$ 下某状态、某状态-动作对的期望回报。
6. **Bellman equation(贝尔曼方程)** 用递归形式刻画价值函数,是几乎所有 RL 算法的基石。
7. **Model-based vs. model-free**:前者已知或学习环境模型 $P,R$(如 DP 动态规划),后者直接从经验学习(如 MC、TD)。
8. **Monte Carlo(蒙特卡洛)** 用完整 episode 的实际回报估计价值;**Temporal Difference(TD,时序差分)** 用自举(bootstrapping)结合单步奖励与下一状态估计。
9. **On-policy vs. off-policy**:SARSA 是 on-policy(评估并改进所执行的策略),Q-learning 是 off-policy(学习最优策略而行为可不同)。
10. **GPI(Generalized Policy Iteration,广义策略迭代)**:策略评估与策略改进交替进行,是 RL 收敛到最优的统一思想。

## 三、关键公式 / 原理

**回报(折扣累积奖励)**
$$G_t = R_{t+1} + \gamma R_{t+2} + \gamma^2 R_{t+3} + \cdots = \sum_{k=0}^{\infty}\gamma^k R_{t+k+1}$$
其中 $R_{t+1}$ 是执行动作后获得的即时奖励,$\gamma$ 是折扣因子($\gamma$ 越接近 1 越重视长远)。

**价值函数定义**
$$V^\pi(s) = \mathbb{E}_\pi[G_t \mid S_t = s], \quad Q^\pi(s,a) = \mathbb{E}_\pi[G_t \mid S_t = s, A_t = a]$$
$\mathbb{E}_\pi$ 表示在策略 $\pi$ 下对轨迹取期望。

**贝尔曼期望方程**
$$V^\pi(s) = \sum_a \pi(a\mid s)\sum_{s',r} P(s',r\mid s,a)\big[r + \gamma V^\pi(s')\big]$$
含义:当前状态价值 = 各动作概率加权下"即时奖励 + 折扣后续状态价值"的期望。

**贝尔曼最优方程**
$$V^*(s) = \max_a \sum_{s',r} P(s',r\mid s,a)\big[r + \gamma V^*(s')\big]$$
**Q-learning 更新(off-policy TD 控制)**
$$Q(s,a) \leftarrow Q(s,a) + \alpha\big[r + \gamma \max_{a'} Q(s',a') - Q(s,a)\big]$$
方括号内为 **TD error(时序差分误差)**,$\alpha$ 是学习率;用 $\max_{a'}Q$ 体现"学习最优策略"。

## 四、典型例子 / 推导

考虑一条三状态链:$s_1 \to s_2 \to s_3$(终止)。在 $s_1$、$s_2$ 只有一个动作"向右",即时奖励均为 $R=1$,$s_3$ 为终止状态 $V(s_3)=0$。取 $\gamma = 0.9$。

用贝尔曼期望方程从后往前回代:
- $V(s_2) = R + \gamma V(s_3) = 1 + 0.9 \times 0 = 1$
- $V(s_1) = R + \gamma V(s_2) = 1 + 0.9 \times 1 = 1.9$

再看一次 Q-learning 更新。设当前 $Q(s_1,\text{右})=0$,$\alpha=0.5$,$\gamma=0.9$。智能体执行动作,得到 $r=1$,落到 $s_2$,且当前 $\max_{a'}Q(s_2,a')=1$。则:
$$Q(s_1,\text{右}) \leftarrow 0 + 0.5\big[\,1 + 0.9\times 1 - 0\,\big] = 0.5 \times 1.9 = 0.95$$
可见单次更新把估计从 0 拉向真值 1.9,随着反复采样会逐步收敛。这就是"边交互边逼近"的核心机制。

## 五、常见误区

1. **把奖励等同于价值**。奖励 $R$ 是单步、即时的信号;价值 $V/Q$ 是长期期望回报。算法优化的目标是价值(长期),而非贪图某一步的高奖励。
2. **认为 $\gamma$ 只是工程技巧**。$\gamma<1$ 不仅保证无限期回报收敛,还编码了"对未来不确定性的折扣",改变 $\gamma$ 会改变最优策略本身。
3. **混淆 MC 与 TD**。MC 必须等 episode 结束用真实回报更新,方差大、无偏;TD 用自举可在线单步更新,方差小但有偏。二者不是同一方法的快慢版本。
4. **把 Q-learning 当成 on-policy**。Q-learning 更新里用 $\max$ 而非实际所选动作,因此学的是最优策略,即便行为策略是 $\epsilon$-greedy 的探索策略,它仍是 off-policy。SARSA 才用实际下一动作 $Q(s',a')$。
5. **忽视探索**。若一开始就纯贪心,智能体可能锁死在次优动作而永不尝试更优解。必须保留探索(如 $\epsilon$-greedy)才能保证充分覆盖。
6. **误以为马尔可夫性总成立**。当状态表示不充分(如只看当前画面而无速度信息)时,问题实为 POMDP(部分可观测),直接套用 MDP 算法会失效。

## 六、与其他知识点的联系

**前置知识**:概率论与期望、马尔可夫链;动态规划(贝尔曼方程本质是 DP 的最优子结构);监督学习中的梯度下降(策略梯度、函数逼近会用到)。理解"期望"与"递归分解"是读懂价值函数的关键。

**横向联系**:RL 与监督学习的区别在于无标签、有交互、奖励延迟;与多臂老虎机(multi-armed bandit)的关系是——bandit 可看作只有单一状态、聚焦探索-利用权衡的特殊 RL。

**后续延伸**:当状态空间巨大时,用神经网络逼近 $Q$ 或 $V$,引出 **DQN(Deep Q-Network)**;直接优化策略参数引出 **Policy Gradient / REINFORCE**;结合价值与策略的 **Actor-Critic**;进一步有 PPO、A3C、AlphaGo 中的 **MCTS + RL** 等。这些都是在本节 MDP、价值函数、TD 思想之上的扩展。

## 七、自测题(含参考答案)

**1.(判断)** Q-learning 是一种 on-policy 算法。
**参考答案**:错误。**解析**:Q-learning 更新目标用 $\max_{a'}Q(s',a')$,学习的是最优策略,与实际执行的行为策略可不同,属 off-policy;SARSA 才是 on-policy。

**2.(选择)** 关于折扣因子 $\gamma$,下列正确的是( )。
A. $\gamma$ 越大越只看即时奖励 B. $\gamma=0$ 时智能体只关心下一步奖励 C. $\gamma>1$ 是常见设置 D. $\gamma$ 不影响最优策略
**参考答案**:B。**解析**:$\gamma=0$ 时 $G_t=R_{t+1}$,仅看即时奖励;$\gamma$ 越大越重视长远(A 错);$\gamma$ 通常取 $[0,1)$(C 错);改变 $\gamma$ 可改变最优策略(D 错)。

**3.(简答)** 简述 MC 与 TD 在更新方式上的本质区别。
**参考答案**:MC 等到一个 episode 完整结束,用实际累积回报 $G_t$ 更新价值,无偏但方差大、需完整轨迹;TD 用单步奖励加上对下一状态的当前估计进行自举更新($R_{t+1}+\gamma V(S_{t+1})$),可在线、单步、方差小,但因依赖估计而有偏。

**4.(计算)** 一条链 $s_a\to s_b\to$ 终止,每步奖励 $R=2$,终止状态价值为 0,$\gamma=0.5$。求 $V(s_a)$。
**参考答案**:$V(s_a)=3$。**解析**:从后往前回代,$V(s_b)=R+\gamma V(\text{终止})=2+0.5\times0=2$;再求 $V(s_a)=R+\gamma V(s_b)=2+0.5\times2=3$。
