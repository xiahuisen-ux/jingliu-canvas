# MiniMax H3 逐秒分镜与视频提示词规则

版本 1.4，更新日期 2026-10-12，时区 Asia/Shanghai。

用途：收到用户剧本后，依据本文生成可审阅的中文详细分镜、每一秒的动作表，以及可交给当前工作台的 H3 英文提示词。本文是官方格式与用户工作流要求的结合，不是 MiniMax 官方原文，也不是视频生成执行程序。用户当次明确要求优先；本规则不能擅自改变剧情、人物、台词、成片时长或启动模型。

## 1 来源与适用范围

官方依据是项目内固定版本的 [H3 Prompt Writing SKILL](studio/h3-prompt-writing/SKILL.md)、[基础模式指南](studio/h3-prompt-writing/references/base-en.txt)与[多参考指南](studio/h3-prompt-writing/references/ref-en.txt)，上游为 [MiniMax H3 官方仓库](https://github.com/MiniMax-AI/MiniMax-H3/tree/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing)，固定提交 d21241f0a4b3acbb34c97dae47fa417b7065e438。本文不声称是最新上游规则。

| 规则来源 | 本文采用内容 |
| --- | --- |
| 官方格式 | 三段基础格式、六段 Ref2VA 格式、英文叙述、参考标签、运镜表达、声音与对白标签 |
| 用户约定 | 每秒动作、场景固定参照物、3/4场景图、人物单张四视图设定图、状态和音色、画面无文字 |
| 当前工作台 | 默认10秒、每段5至15秒、单段一个连续镜头、规划三段后渲染绑定实际参考、最多9张图片 |
| 尾帧优化 | 工作台支持 Qwen-Image-Edit-2511 多图重绘：尾帧主构图＋1–2位角色外貌参考，8步；自动接续/先预览再采用。只有已生成的实际结果才可声明完成，身份和画质仍需核验 |

逐秒描述是创作目标，不是模型的确定性时间控制。不能保证动作严格在某一秒发生、音色完全相同或衔接像素级无缝。实拍般连续性仍需生成后检查与必要的剪辑。本文中的秒数和距离是调度描述，不是三维几何控制接口。

2026-10-12 分段范围补充：每个视频任务只保留本段起始状态、逐秒动作、镜头、说唱与结束状态，以及必要的简短角色/空间设定。整片梗概、其他段的动作台词和完整角色成长过程不得复制进每个描述框。静态设定在本段说明一次即可，各秒仅写本秒动作和变化，仍须完整覆盖每一秒。已配套校验的中英文不重复拼接送入H3；之后的新编辑必须继续生效。绑定原声时由该段录音提供音色，避免另加含全片剧情的声音备注。提示词缩短不等于已经证明GPU或系统卡顿恢复。

## 2 收到剧本后的工作顺序

1. 读取本文。涉及当前工程时，再读工作流总览与工程现有剧本、角色、选图、镜头时长；不把旧默认值覆盖到新设置。
2. 提取剧情目标、必须保留的事件与台词、人物状态、场景转换、目标总时长、画幅和声音要求。
3. 缺少细节时，只补与原文兼容的动作、调度和环境，列为“创作假设”。关键身份、剧情结局或总时长有实质歧义时提一个简短问题；不要为了小细节阻塞整份分镜。
4. 先列角色物品表、场景参照物表、镜头总表，再逐段展开。用户给定时间线时先沿用，不机械地每10秒剪断台词或动作。
5. 输出每段中文逐秒表与英文三段提示词，保持二者人物、时间、动作、相对位置、声音完全一致。
6. 交付前按第11节检查；只生成文档，不自动跑生图、视频或改工程数据。

总时长未指定时，注明“本次建议总时长”及假设，不冒称用户已确认。默认按10秒规划，每段可在5至15秒内调整。固定总时长不是10的倍数时，重新分配临近段落，不增加不足5秒的任务，也不悄悄延长成片。例如23秒可拆10秒加13秒。用户要求短于5秒时明确当前工作台限制，可提出生成5秒后剪辑的方案，不自行改变交付。

## 3 角色物品与场景设定

### 角色和物品表

每个角色固定一个创作编号，如 CHAR_A；实际工程已有ID时另外保留真实ID映射，不能用创作编号覆盖工程ID。列出姓名、外貌、基础服装、当前状态、随身物品、音色提示词、参考图是否已提供。关键物品列外观、所在场景、持有者及左右手。

受伤、铠甲、机甲、换装、年老或年少属于同一角色的状态。每段明确选用哪个状态，以及变化是否发生在段内。选定状态覆盖冲突的基础服装或年龄描述，但保留身份；需要变身过程时，写变化顺序，不能只给开始与结束两种静态状态。

人物新图按单张四视图使用：从左到右为加宽脸部高清特写、正视颈部以下无头部、完整侧面全身、完整背面全身；四栏宽度2:1:1:1，只有一排，特写栏不再分小图。四栏是同一人物，特写提供唯一面部身份，正视栏只提供服装体型，展示/下载图的侧背栏保留正常头部；实际视频输入的video-reference.png另将侧背头部遮除，只从左侧高清特写读取脸部。四栏由四次单视图生成后程序按2:1:1:1拼版，完整脸部contain放入，不居中裁断。颈线必须预览；不合适可保存裁切新版本。视频人物始终有正常头脸，不复制正视栏的头部留空。已生成的旧完整正面四视图仍按其旧布局使用。视频不复制设定图布局或多个角色。旧人物三栏图仍沿用原有约定：左栏是唯一面部特写来源；中栏正面颈部以下至脚部只提供服装与体型；右栏背面全身提供后侧服饰与发型。生成视频必须是正常完整头脸的单个人物，不复刻三栏、无头展示、文字或标签。未经看图，不断言实际图片符合此布局。

### 场景和固定参照物表

每个地点定义一个稳定、明显、可辨认的参照物，如有铜色底座的红色落地灯、方形立柱、黄色沙发。优先选择剧情已经有的物体，不必无端添加柱子。场景图优先3/4斜角，展示纵深、参照物及关键物件，不将3/4角度强制套用到后续所有视频机位。

固定世界方向以首次场景建立视角为基准：左、右、近侧、远侧。近侧指朝初始机位的方向；远侧指背离初始机位。摄影机旋转后世界方向不变，画面左/右须另写，不能与世界方向混用。

每个场景至少列：场景ID、参照物ID及特征、初始观察方向、主要角色起点、关键物品位置、出口方向、光源方向。人物和关键物品使用“相对参照物的方向＋约距离＋姿态/朝向”。静态位置可以在场景表定义并由各秒继承，不必反复抄写；不能只写“站在那边”。

合格示例：CHAR_A站在红灯近侧约1.2米、左侧约0.6米，右手持合拢信封，身体朝红灯；沙发位于红灯远侧约1.5米。人物向红灯靠近0.3米后停下，沙发与红灯始终不移动。

不合格示例：人物在左边，摄影机绕到另一边，人物仍在左边。此表述没有区分世界方向与画面方向。

## 4 每秒动作规则

每个时长为D秒的任务输出D行：0至1秒、1至2秒，直到D减1至D秒。所有区间连续、无遗漏、无重叠；英文统一用 `During 0-1 seconds:` 等标记，标记后必须有动作正文。工作台兼容等价的逗号、s/sec、整数小数与时间范围标题，并只规范标记，不补写缺失动作。段内时间从0重置，同时提供在全片中的时间范围。边界表示动作交接，不要求重复执行边界瞬间。

每行至少包含以下五项：

| 项目 | 写法 |
| --- | --- |
| 人物与物体动作 | 谁、哪只手或哪条腿、开始状态、可见动作、结束状态 |
| 相对位置与视线 | 相对固定参照物的位置是否变化，面向谁，视线落点 |
| 镜头 | 景别、机位或运镜的本秒变化；固定时明确固定 |
| 声音 | 台词所在时段、说话者，脚步或接触声；无对白明确无对白 |
| 交接状态 | 此秒末手持物、姿态和运动趋势，下一秒不得无故重置 |

每秒写清楚不等于每秒制造一个新事件。跨数秒的动作按准备、启动、发展、接触、收束拆开；停顿写呼吸、目光或保持姿态。不要把“起身、绕柱、拔剑、挥砍、转身”塞进一秒。默认每段围绕一个主要事件，给表情反应和动作完成留出时间。

动作顺序遵循接近后接触、握住后拿起、松手后物体才离手等因果。持续移动要与距离和时长匹配；没有剧情理由，不增加人物、换手、移动家具、改变伤口或装备。需要同时发生的动作说明主次，避免摄影机与多个角色同时高速复杂运动。

## 5 运镜与连续性

当前工作台每段是一个连续镜头，英文仅有一个 `[Shot 1]`。段落编号如SEG_003不是模型的 `[Shot 3]`。先建立构图，再按秒描述动作；需要真正切镜时拆成下一段，不以每秒一切代替逐秒动作。

运镜写类型、必要的幅度和速度：缓慢小幅推进、向右平移约半米、小幅绕行等。区分推近与变焦、平移与摇镜。为降低旋转时身份漂移，优先可读的小幅运动；故事要求大幅绕拍时写清起止角度、速度、参照物和角色朝向，并标记高风险，不承诺参考图能彻底消除变形。

同场连续段的接续表记录上一段结束姿态、下一段起始姿态、手持物、视线、服装状态、参照物位置、光照、摄影机方向和声音延续。最后一秒保留可衔接的明确状态；不强制所有镜头停住，需要运动衔接就保持运动方向和速度。

全能参考模式继承上一段实际尾帧作为构图与内容参考；首尾帧模式可明确选择上一段接续图作为首帧锚点。Qwen优化启用时使用已生成且有效的优化版，否则按所选策略等待重绘或采用原图；不要混淆模式。没有生成上一段时，只写“待生成后提取实际尾帧”，不能虚构路径或已经增强。换场、时间跳跃或主动切换构图时建议关闭继承并说明原因。

## 6 角色声音和无文字画面

每个角色有一段稳定音色描述：音高范围、共鸣、质感、语速、发音/口音；情绪强弱放到本段表演中，不每段更换基本音色。没有声音样本时是创作设定，不是从照片识别音色，也不是声纹克隆。

角色出现时带入音色约定；没有对白就注明本段不发声，不让音色说明诱发额外讲话。人物真正说话、唱歌或画外发声时，才分配稳定的 `(S1)`、`(S2)`。按整份目标作品首次发声顺序登记，并在后续任务保持映射；没有发声的人不分配说话者编号。

英文视觉叙述中保留中文原台词，形式为 `<d>[Chinese] 原台词</d>`。动作、情绪、音色、说话者编号放在标签之外。台词跨数秒时只完整写一次，并在逐秒表注明持续范围，不能每秒重复整句话。原台词太长时调整任务时长或建议拆段，不擅自删字或加速到不自然。

对白栏可同时包含实际台词和声音制作说明，二者不可混为一谈。明确“删除某句人声”“不唱某句”时，被引用的句子属于排除内容，不得为了通过校验补回；“不要删除某句”属于保留要求。程序对明确表述提取必须说唱与排除清单，含义不明时保守处理，不把复杂时序条件视为整段禁唱。英文原台词仅在正文对白标签中写出，声音总结只用英文指代；已在正文正确标注的同句若在声音总结重复引用，可机械替换为英文指代，不移动发声时刻、不改词或录音。

旁白与对口型分开：官方旁白写法使用 `says in an off-screen voiceover`；同角色可见时补充嘴唇保持闭合。跨实际切镜的语音和截断标记按官方指南处理；当前逐段独立生成不保证跨段音频无缝，长旁白或歌曲可作为待后期统一音轨，不谎称已经混音。

默认图像与视频无字幕、标注、水印、角色ID和参考图标签。声音提示词不等于画面文字。用户明确改变此要求时再调整，不把剧本中的台词自动变成字幕。

## 7 H3 官方格式与工作台粘贴边界

### 规划阶段使用三段

当前工作台的动作时序字段 `motion_prompt` 接收一个字符串，按以下顺序且字段不得缺失。中文表供审阅，下面的英文块供生成，两者不能互相矛盾。

```text
integrated_multimodal_description: [Shot 1] English style and opening composition. Describe the continuous action with one-second intervals inside this same shot. Include positions, camera movement, acting, dialogue and synchronized sound.

overall_soundscape: English description of continuous ambience and physical sounds.

non_diegetic_music: N/A
```

第一镜头标记本身不加剪切时间戳；后面的 `During 0–1 seconds...` 是本地逐秒动作表达，不是新增镜头标记，也不是官方独立控制字段。三段格式字段之外不要插入自创第四个字段。无参考图时不能编造 `<Picture N>`、`<Subject N>`、`<Audio N>` 或 `<Video N>`。

环境声使用1至4句完整英文，台词留在第一段，不重复在声音总结中。仅当整段完全静音时 `overall_soundscape` 才写 `N/A`。无画外配乐时 `non_diegetic_music` 写 `N/A`；有配乐则写乐器、速度和动态。剧情中的收音机等有源音乐属于第一段的现场事件。

### 最终多参考模式使用六段

实际图片清单与顺序确定后，Ref2VA采用以下顺序：

```text
subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:
```

这些是结构示意，不是可直接生成的空提示词。实际每段都须填写。`summary` 的任务类型来自实际参考用途；只有图片参考时通常为 `[reference generation]`，提取的单张尾帧不等于把原视频作为 `<Video 1>` 输入。

`<Subject N>`代表人物、物体、场景等可复用内容；`<Picture N>`按实际传图顺序绑定。人物图只提供身份外观时，在Subject定义中指出图片来源，不必为它再建独立Picture条目。图片承担构图或实际帧锚点时才另作定义。视频与音频标签只用于真实输入，不因有音色文字就编造音频文件。

`retention_analysis` 的视觉关系可用 `fully_preserved`、`partially_preserved`、`attribute_transfer`、`weak_reference`；音频关系可用 `fully_copy`、`partially_copy`、`reference`、`weak_reference`。根据真实保留关系选择，角色换装不能声称原服装完全保留。官方多参考正文通常350至500英文词，以具体可执行内容为准，不为凑字数填充剧情或重复台词。

本地渲染器会把三段规划稿结合实际图序转换为六段。不要将手写六段稿粘到当前要求三段的 `motion_prompt` 输入框。用户要求独立最终Ref2VA稿时，先确认完整图序，再输出六段并注明它不是当前规划输入格式。上游I2VA、FL2VA、L2VA有各自首尾帧对齐指令；当前仅上传参考图不等于启用这些模式，不擅自添加硬性对齐声明。

## 8 参考图分配

规划表使用人物、场景、物品ID与用途，不提前填写最终Picture编号。可分为：连续性主参考（上一段实际尾帧）、角色身份辅助参考（所选状态）、场景空间参考、关键物品参考、外部补充照片。

人物、物品和场景图都属于文生视频的辅助参考，不作为主参考图或首帧。参考图提供角色外貌、服装和环境特征，构图、站位、动作与摄影机角度依照本段文字。元素页自由新增内容会进入各视频任务调用列表，按段勾选；不能因清单中存在某元素就让它出现在每一段。图库“图片重绘原图”只服务于图片重绘，不改变视频参考用途。

当前最多9张图片是工作台约束，不宣称所有H3实现都一样。超限先列出哪些参考对当前画面必要，再让用户确认精简；不要静默丢图。只选会影响本段可见内容的元素，不因某角色存在于全剧就让其出现在每段。

参考图未知或没提供时写“待提供”，不能推测照片中的姿态和细节。未经图片检查不声称脸部、背面或3/4角度正确。角色状态、原图和前段尾帧冲突时说明冲突及采用策略，不同时要求互斥外观。

## 9 标准交付结构

后续收到剧本时，按下列顺序输出：

1. 创作假设和未决项：总时长、分段、风格、声音与保留内容。
2. 人物和关键物品清单：稳定ID、外观、状态、音色、参考状态。
3. 场景参照物表：固定方向、人物与关键物件初始相对位置。
4. 镜头总表：编号、全片起止时间、时长、剧情目的、调用元素、参考继承策略。
5. 每段详细镜头卡：起始构图、角色状态、逐秒动作表、英文三段提示词、结束状态和接续条件。
6. 生成前检查与高风险项：缺图、动作密度、旋转、长对白、转场和未实现能力。

每段逐秒表使用“本段时间｜动作与视线｜相对位置｜镜头｜声音”五列；交接状态写进动作栏，段末再汇总。10秒必须有10行，不能以“1至8秒继续活动”代替。整片太长时可分批交付，但明确本批覆盖范围和未完成段落，不称已完整交付。

## 10 完整十秒示例

本例为创作示范，不是对已有作品的改写。目标：女主在室内红灯旁举起信封后望向门口，10秒连续固定镜头，无对白与音乐。场景LOC_01、人物CHAR_A、信封PROP_01、参照物ANCHOR_01。全片位置0至10秒。

CHAR_A：25岁东亚女性，齐肩黑发，米白风衣，深灰长裤。稳定音色设定为自然中低音、清晰普通话、轻微气声、平稳语速；本段不发声，不分配S编号。右手持合拢的米色无字信封，全段不换手。

ANCHOR_01：铜色底座的红色落地灯。以初始机位定义世界方向。CHAR_A在灯左侧约0.6米、近侧约1.2米；空门口在灯右侧约2米、远侧约1米。灯和门口全段不动，女子双脚全段不移位。固定中全景，平视机位，3/4观察房间，暖灯光与窗侧冷光保持稳定。

| 本段时间 | 动作与视线 | 相对位置 | 镜头 | 声音 |
| --- | --- | --- | --- | --- |
| 0至1秒 | 女主右手垂持信封贴近右大腿，目光略向下，呼吸平稳 | 灯左0.6米、近侧1.2米，双脚固定 | 固定中全景，灯与门口可辨 | 持续轻微室内底噪，无对白 |
| 1至2秒 | 目光下移至信封，头缓慢下倾，手尚未举起 | 不变 | 保持固定 | 底噪，无额外动作声 |
| 2至3秒 | 右肘开始弯曲，信封从大腿旁升至腰部，左臂自然下垂 | 双脚及躯干位置不变 | 固定，手部动作在画内 | 轻微袖料摩擦 |
| 3至4秒 | 同一抬手动作延续，信封升至下胸处后减速 | 不变，信封始终在右手 | 固定，不切特写 | 衣料声逐渐收束 |
| 4至5秒 | 信封停在下胸位置，右拇指轻触封口边缘但不打开 | 不变 | 固定 | 一次轻微纸张摩擦 |
| 5至6秒 | 右拇指停止，女主缓慢吸气，目光仍落在信封上 | 不变 | 固定 | 轻微吸气，无台词 |
| 6至7秒 | 眼睛先抬起转向灯右侧远处的门口，头开始轻抬 | 双脚固定，不转身 | 固定，门口仍在构图内 | 底噪持续 |
| 7至8秒 | 头部小幅转向门口，身体不随之旋转，右手稳持信封 | 人物和灯距离不变 | 固定 | 轻微呼吸，无新增脚步 |
| 8至9秒 | 视线稳定落在空门口，信封保持下胸高度，嘴唇闭合 | 不变，门口仍在灯右侧远侧 | 固定 | 底噪，无对白 |
| 9至10秒 | 保持看门口的姿态，自然呼气，动作平稳收束 | 同上一秒，无物体移动 | 固定，保留接续构图 | 呼气与底噪延续到末尾 |

配套工作台三段提示词如下；尚未绑定图片编号，不能据此声称已经使用参考图。

```text
integrated_multimodal_description: [Shot 1] Live-action realism, one uninterrupted ten-second shot. An eye-level, static medium-wide composition views the room from a three-quarter angle, keeping the woman's hands, a red floor lamp with a brass base, and an empty doorway readable. A 25-year-old East Asian woman has shoulder-length black hair, a cream trench coat and dark-gray trousers. Use the lamp as the fixed spatial anchor. Left, right, near and far remain defined by this initial camera view. She stands about 0.6 metres left of the lamp and 1.2 metres on its near side; the doorway is about 2 metres right of the lamp and 1 metre on its far side. Her feet, the lamp and the doorway remain fixed throughout. Warm lamplight and soft cool window light stay constant. During 0–1 seconds: she holds one closed, unmarked beige envelope beside her right thigh in her right hand, with lowered eyes and steady breathing. During 1–2 seconds: her eyes settle on the envelope and her chin lowers slightly while her hand stays down. During 2–3 seconds: her right elbow bends and the same envelope rises to waist height; her left arm remains relaxed, with a faint sleeve rustle. During 3–4 seconds: the uninterrupted lift continues to her lower chest and gently decelerates. During 4–5 seconds: she holds it there and brushes its closed edge once with her right thumb, producing a small paper rustle without opening it. During 5–6 seconds: her thumb stops and she inhales softly, still watching the envelope. During 6–7 seconds: her eyes lift toward the doorway on the lamp's far-right side and her chin begins to rise. During 7–8 seconds: her head turns slightly toward that doorway without rotating her torso or moving her feet. During 8–9 seconds: her gaze settles on the empty doorway while her right hand holds the envelope steadily at her lower chest and her lips remain closed. During 9–10 seconds: she maintains that same pose and exhales gently, leaving a clear continuation state. The camera remains completely static without cuts or zoom. Her established voice would be a natural mid-low register with clear Mandarin articulation, light breathiness and measured delivery, but she does not speak or sing in this clip. Show one complete person with a normal head and face, stable clothing and natural anatomy; no reference-sheet layout, captions, writing, logos or watermarks appear.

overall_soundscape: Quiet room tone continues throughout. A faint sleeve rustle accompanies the lift, one soft paper friction sound occurs when her thumb touches the envelope, and restrained breathing follows the described action. No speech, singing or footsteps.

non_diegetic_music: N/A
```

结束接续记录：人物仍在灯左侧0.6米、近侧1.2米，右手在下胸处持未开信封，目光朝灯右侧远处门口，嘴唇闭合。下一段若同场延续，先保持这些状态，再展开下一动作；实际视频若偏离本表，先检查实际尾帧，不以计划状态冒充已经生成的状态。

## 11 交付前检查

- 每段时长在当前允许范围，总时长与镜头表相加一致；全片时间无遗漏或重叠。
- 每段D秒恰有D条一秒区间；英文时间线与中文逐秒表一致，不漏秒。
- 人物ID、状态、物品持有者、用手、视线和音色跨段一致，改变都有剧情原因。
- 主要人物和物件均可定位到固定参照物；世界方向不因运镜改变，静态物件不会漂移。
- 单段只有一个Shot 1，没有额外切镜；无动作堆积和明显不可能的移动。
- 三段字段顺序正确且非空；英文叙述，台词原语言，所有d标签闭合。
- 静音、环境声、对白、旁白和配乐不矛盾；未凭空增加讲话者或台词。
- 图序未定不编造参考标签、路径或文件；图数与现有后端上限相容。
- 明确前段继承还是换场，检查末秒与下段开头状态；不承诺强制首帧或已完成高清重绘。
- 文档中的无文字、按新旧设定图布局读取身份、低风险运镜等是提示词要求，不伪称已通过实际生成验收。

