import os  # 导入操作系统接口模块，用于读取环境变量和拼接路径

# ================= 1. 数据库配置 =================
# 【重点思想】：os.getenv("环境变量名", "默认值")
# 这是一种极其优雅的写法：
# 1. 在本地开发时，你没有配置环境变量，它就会用后面的默认值（比如 127.0.0.1, root, 123456）。
# 2. 当你把项目部署到云服务器（或 GitHub Actions）时，只需要在服务器上设置好环境变量，
#    代码一行都不用改，就能自动连上服务器的线上数据库！这就是著名的 "12-Factor App" 配置分离原则。

# MySQL 主机地址，默认本机
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
# MySQL 端口，默认 3306。注意外面套了一层 int()，因为从环境变量读进来的都是字符串，要转成数字
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
# 数据库用户名，默认 root
MYSQL_USER = os.getenv("MYSQL_USER", "root")
# 数据库密码，默认 123456
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
# 数据库名，默认 farm_mall
MYSQL_DB = os.getenv("MYSQL_DB", "farm_mall")

# ================= 2. Flask 应用密钥 =================
# 这个密钥我们之前在 app.py 里见过了，它用来加密 Flask 的 session（也就是用户的登录状态 Cookie）。
# 同样使用了环境变量：上线时一定要在服务器配置一个随机的、长一点的复杂环境变量覆盖这个默认值，防止被破解。
SECRET_KEY = os.getenv("SECRET_KEY", "farm_mall_secret_key_please_change")

# ================= 3. 文件上传配置 =================
# 【重点语法】：动态路径拼接
# os.path.dirname(__file__) 获取当前 config.py 所在的目录（也就是项目根目录）。
# 然后依次拼接 static 和 uploads。
# 为什么要这么麻烦？因为你在 Windows 上可能是 D:\project\static\uploads，在 Linux 上是 /home/project/static/uploads。
# 用 os.path.join 会自动适配当前操作系统的斜杠方向，绝不出错！
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")

# 允许上传的图片后缀名集合。这是一个 Python 的 Set（集合），查询速度极快。
# 我们之前在 app.py 的 allowed_file 函数里就是拿它来校验用户传的文件合不合法
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}