# 导入 PyMySQL，这是一个纯 Python 实现的 MySQL 客户端库
import pymysql
# 从 config.py 导入数据库配置信息
from config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB


def get_db(database=True):
    """
    获取 MySQL 连接
    database=False 用于第一次初始化时（因为此时 farm_mall 这个数据库还没被创建，不能连进去）
    """
    # 把连接参数打包成字典
    kwargs = dict(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",  # 【重点】：必须用 utf8mb4！普通的 utf8 在 MySQL 里不支持存 Emoji 表情和一些生僻字
        # 【重点】：DictCursor（字典游标）。
        # 默认情况下 PyMySQL 查出来的数据是元组，比如 (1, '苹果', 5.0)，你只能用 result[1] 取名字，极易出错。
        # 设成 DictCursor 后，查出来的是字典，比如 {'id': 1, 'name': '苹果', 'price': 5.0}，你可以直接用 result['name'] 取值，爽！
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,  # 【重点】：关闭自动提交。这意味着所有的增删改操作，必须手动调用 conn.commit() 才会真正生效。
                           # 这是为了支持我们在 app.py 里看到的“事务”操作（比如下单时扣库存、清购物车要同时成功或同时失败）。
    )
    if database:
        kwargs["database"] = MYSQL_DB  # 如果指定了连具体数据库，就把参数加上
        
    return pymysql.connect(**kwargs)  # 解包字典，建立并返回数据库连接


def query_one(sql, args=None):
    """执行查询，只取一条结果 (比如查某个用户、某件商品)"""
    conn = get_db()  # 借一个连接
    try:
        with conn.cursor() as cursor:  # 打开游标（with 语法确保游标用完自动关闭）
            cursor.execute(sql, args or ())  # 执行 SQL 语句，args 是防止 SQL 注入的参数
            return cursor.fetchone()  # 抓取第一条结果并返回
    finally:
        conn.close()  # 【重点】：无论上面成不成功，最后必须把连接还回去（关闭），防止连接泄露撑爆数据库


def query_all(sql, args=None):
    """执行查询，取出所有结果 (比如查商品列表、订单列表)"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, args or ())
            return cursor.fetchall()  # 抓取所有结果，返回一个包含多个字典的列表
    finally:
        conn.close()


def execute(sql, args=None):
    """执行增、删、改操作 (比如注册用户、修改库存、删除商品)"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, args or ())  # 执行更新操作
            conn.commit()  # 【重点】：因为前面关了 autocommit，这里必须手动提交，数据才会真正写进硬盘
            return cursor.lastrowid  # 返回新插入那条数据的自增 ID（比如注册新用户时，直接返回他的 user_id）
    except Exception:
        conn.rollback()  # 【重点】：如果执行中途报错了，马上回滚！撤销刚才所有的修改，保护数据一致性
        raise  # 把错误继续往上抛，交给 app.py 里的 try...except 去处理
    finally:
        conn.close()