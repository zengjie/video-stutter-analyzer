# 视频卡顿分析器

分析游戏录像中的画面卡顿，检测重复帧并计算流畅度评分。

## 功能

- 上传视频自动分析帧时间
- 检测重复帧（基于 EMA 自适应阈值）
- 运动感知的卡顿检测（只标记动画中的重复帧）
- 流畅度评分（0-100）
- 可视化时间轴标记卡顿位置
- 逐帧播放验证
- 飞书 OAuth 登录认证

## 分析指标

| 指标 | 说明 |
|------|------|
| 平均帧率 | 基于有效帧时间计算 |
| 1% 最低 | 最差 1% 帧的帧时间 |
| 重复帧 | 与前一帧几乎相同的帧数量 |
| 卡顿数 | 动画过程中出现的重复帧事件 |

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 命令行分析
python main.py video.mp4

# JSON 输出
python main.py video.mp4 --json

# 启动 Web 服务
uvicorn app:app --reload
```

## 部署到 Railway

1. Fork 或推送代码到 GitHub
2. 在 Railway 创建项目，连接 GitHub 仓库
3. 配置环境变量（见下方）
4. 自动部署完成

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `SESSION_SECRET` | Session 签名密钥（随机字符串） |
| `REDIRECT_URI` | OAuth 回调地址，如 `https://your-app.railway.app/callback` |

## 飞书应用配置

1. 访问 [飞书开放平台](https://open.feishu.cn/app) 创建应用
2. 记录 App ID 和 App Secret
3. 在「安全设置」中添加重定向 URL
4. 在「权限管理」中开启：
   - 获取用户 userid
   - 获取用户基本信息

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `,` | 上一帧 |
| `.` | 下一帧 |
| `[` | 上一个卡顿 |
| `]` | 下一个卡顿 |
| `空格` | 播放/暂停 |

## 技术栈

- Python 3.11
- FastAPI
- OpenCV (headless)
- NumPy
- itsdangerous (session)

## License

MIT
