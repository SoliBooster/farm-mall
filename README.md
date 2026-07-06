# 🌾 Farm Mall

> 一个基于 Flask + MySQL 的助农电商平台，实现了用户系统、购物车、订单管理以及基于混合推荐算法的个性化商品推荐。

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-green)
![MySQL](https://img.shields.io/badge/MySQL-5.7%2F8.0-orange)
![License](https://img.shields.io/badge/License-MIT-red)

本项目最初源于作者的本科毕业设计《基于混合推荐算法的助农商城设计与实现》。

毕业设计完成后，作者决定将项目持续维护并开源，希望能够帮助更多学习 Flask、电商系统开发以及推荐算法的同学，也欢迎大家共同交流和完善。
## 一、功能概览

- 商城首页：左侧分类、中心商品板块、右侧热卖榜、搜索框、为你推荐
- 商品详情：显示商品图片、类别、产地、价格、库存、卖家、浏览量、销量；支持购买、加入关注、退出
- 购物车：未登录不可用；支持查看商品、修改数量、移除商品、去结算
- 订单流程：确认订单、填写收货信息、提交订单、查看订单详情、取消待处理订单、确认收货
- 我的订单：展示用户所有订单及状态
- 我的关注：展示用户关注的商品
- 我要卖货：支持上传商品图片、名称、类别、价格、库存、产地、介绍；支持管理自己发布的商品
- 卖家管理：编辑商品、上下架商品、删除商品、查看近期售出记录
- 登录/注册：用户名 1-10 位；密码 8-18 位，必须包含大小写字母和数字
- 用户信息：可修改性别、电话、地址；展示上传记录、购买记录、搜索历史
- 后台管理：管理员可查看系统统计、管理商品、管理订单、查看用户
- 推荐模块：结合用户行为、商品热度、时间因素与类别偏好，生成个性化推荐结果

除常规商城功能外，本项目重点实现了基于用户行为分析的混合推荐算法，综合考虑：

- 浏览行为
- 搜索行为
- 收藏行为
- 购买行为
- 商品类别偏好
- 商品热度
- 时间衰减因素

最终融合多种特征，为不同用户生成个性化推荐结果。

推荐算法实现位于：

```text
recommender.py
```

## 二、运行环境

推荐环境：

- Ubuntu 20.04
- Python 3.8+
- MySQL 8.0 或 5.7

## 三、快速运行

### 1. 进入项目目录

```bash
cd farm_mall_v3
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

如果 Ubuntu 提示 externally-managed-environment，请确认已经进入虚拟环境后再安装依赖。

### 4. 修改 MySQL 配置

打开 `config.py`，将下面几项改成你的 MySQL 信息：

```python
MYSQL_USER = "root"
MYSQL_PASSWORD = "123456"
MYSQL_DB = "farm_mall"
```

### 5. 初始化数据库

```bash
python init_db.py
```

初始化成功后会生成测试账号：

```text
管理员账号：admin / Admin123456
普通用户账号：小农户 / User123456
```

### 6. 启动项目

```bash
python app.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

云服务器部署时访问：

```text
http://服务器公网IP:5000
```

## 四、项目结构

```text
farm_mall_v3/
├── app.py                    # Flask 主程序，包含路由和业务逻辑
├── config.py                 # MySQL、上传路径、密钥配置
├── db.py                     # 数据库连接工具
├── recommender.py            # 混合推荐模块
├── init_db.py                # 初始化数据库与测试数据
├── schema.sql                # 数据库建表语句
├── requirements.txt          # 依赖包
├── static/
│   ├── css/style.css         # 全站样式
│   ├── img/default_product.svg
│   └── uploads/              # 用户上传图片保存目录
└── templates/
    ├── base.html             # 公共模板
    ├── index.html            # 商城首页
    ├── product_detail.html   # 商品详情
    ├── cart.html             # 购物车
    ├── cart_detail.html      # 购物车商品详情
    ├── checkout.html         # 确认订单
    ├── orders.html           # 我的订单
    ├── order_detail.html     # 订单详情
    ├── favorites.html        # 我的关注
    ├── sell.html             # 我要卖货/卖家中心
    ├── edit_product.html     # 编辑商品
    ├── login.html            # 登录
    ├── register.html         # 注册
    ├── profile.html          # 用户信息
    ├── admin_dashboard.html  # 后台首页
    ├── admin_products.html   # 后台商品管理
    ├── admin_orders.html     # 后台订单管理
    ├── admin_users.html      # 后台用户管理
    └── 404.html              # 自定义 404 错误页
```

## 五、AIGC声明

本项目的设计、重构与完善过程中，借助了 ChatGPT-5.5、GLM-5.2、deepseek-V4 的协助完成了部分架构设计、代码优化与文档整理相关工作。

最终方案均经过作者理解,验证和实现。

## 六、开源许可证

本项目遵循 **MIT License** 开源协议，详情请参阅项目根目录下的 `LICENSE` 文件。

## 七、欢迎贡献

欢迎通过以下方式参与项目建设：

- 提交 Issue 反馈 Bug
- 提出功能建议
- 提交 Pull Request
- 完善文档

如果这个项目对你的学习有所帮助，欢迎点一个 ⭐ Star，这将是作者持续维护项目最大的动力。

## 八、致谢

感谢所有在项目开发过程中给予帮助的人。
