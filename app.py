# ================= 1. 导入必要的模块 =================
import os
import re  # 正则表达式模块，用于校验用户名、密码格式
import uuid  # 生成唯一字符串，用于给上传的图片重命名
from decimal import Decimal  # 用于精确的小数计算（电商算钱必备，防浮点数误差）
from datetime import datetime  # 处理时间，比如订单创建时间
from functools import wraps  # 用于编写装饰器时保留原函数的元信息

# Flask 核心组件及工具
from flask import Flask, render_template, request, redirect, url_for, session, flash
# werkzeug 是 Flask 底层的 WSGI 工具库，这里用到了安全相关的密码哈希和文件名处理
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# 从本地文件导入配置和数据库操作（说明项目结构分明了，配置和数据库操作被抽离到了单独的文件）
from config import SECRET_KEY, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
from db import query_one, query_all, execute, get_db
from recommender import get_recommendations # 导入推荐系统模块（为你首页的"为你推荐"提供数据）

# ================= 2. 初始化 Flask 应用 =================
app = Flask(__name__)  # 创建 Flask 应用实例
app.secret_key = SECRET_KEY  # 设置密钥，Flask 的 session (会话) 加密全靠它，不能泄露
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER  # 配置文件上传保存的文件夹路径
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # 确保上传文件夹存在，exist_ok=True 表示如果已存在不报错(已放在gitignore里)

# ================= 3. 定义正则表达式规则 (前端也有对应的提示) =================
# 用户名规则：1-10位的汉字(\u4e00-\u9fa5)、大小写字母或数字
USERNAME_RE = re.compile(r'^[\u4e00-\u9fa5A-Za-z0-9]{1,10}$')
# 密码规则：8-18位，且必须同时包含大小写字母和数字
PASSWORD_RE = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,18}$')
# 电话规则：允许数字、连字符、加号和空格，长度6-30位（比较宽容，兼容国内外座机和手机）
PHONE_RE = re.compile(r'^[0-9\-+ ]{6,30}$')

# ================= 4. 文件上传与处理工具函数 =================
def allowed_file(filename):
    # 检查上传的文件后缀名是否在允许的列表内 (如 png, jpg等)
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(image_file, old_path=None):
    """
    保存用户上传的图片文件
    image_file: 前端传过来的文件对象
    old_path: 如果是编辑商品，传入原图片路径。如果用户没传新图，就保留老图
    """
    # 如果没有传文件，或者文件名是空的，返回旧路径；如果没有旧路径，返回一个默认占位图
    if not image_file or not image_file.filename:
        return old_path or 'img/default_product.svg'
    
    # 校验文件格式是否合法
    if not allowed_file(image_file.filename):
        raise ValueError('图片格式只支持 png、jpg、jpeg、gif、webp。')
    
    # secure_filename 会清理文件名中的危险字符（防黑客在文件名里写恶意路径）
    # 然后提取出后缀名
    ext = secure_filename(image_file.filename).rsplit('.', 1)[1].lower()

    # 使用 uuid 生成一个完全不重复的随机字符串作为新文件名，防止重名覆盖
    filename = f"{uuid.uuid4().hex}.{ext}"

    # 把文件真正保存到服务器的 UPLOAD_FOLDER 文件夹里
    image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    # 返回给数据库存储的相对路径 (比如 "uploads/abcd1234.jpg")
    return f"uploads/{filename}"

# ================= 5. 用户会话与权限控制 (核心重点!) =================
def current_user():
    """
    获取当前登录的用户对象
    前端模板里的 current_user 就是调用了这个函数（通常是通过上下文处理器注入的）
    """
    uid = session.get('user_id')  # 从浏览器的 Cookie 会话中取出 user_id
    if not uid:
        return None # 没登录就返回 None
    # 根据 user_id 去数据库查完整的用户信息
    return query_one("SELECT * FROM users WHERE id=%s", (uid,))


def login_required(f):
    """
    登录验证装饰器
    把它加在路由函数上面，就能强制要求用户必须登录才能访问该页面
    """
    @wraps(f)  # 保留原路由函数的名字和文档，防止 Flask 路由注册报错
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):  # 检查 session 里有没有 user_id
            # 没登录就弹个提示，并踢回登录页
            flash('请先登录后再使用此功能。', 'warning')
            return redirect(url_for('login'))
        # 如果登录了，就正常执行原本的路由函数
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """
    管理员验证装饰器
    把它加在路由函数上面，不仅要求登录，还要求该用户的角色必须是 'admin'
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()  # 获取当前用户
        if not user or user.get('role') != 'admin':  # 如果没登录，或者角色不是管理员
            # 提示没权限，并踢回首页
            flash('你没有后台管理权限。', 'danger')
            return redirect(url_for('index'))
        # 验证通过，正常执行原函数
        return f(*args, **kwargs)
    return wrapper

# ================= 6. 用户行为日志记录 (推荐系统的数据来源) =================
def log_action(user_id, product_id=None, action_type='view', score=1.0, keyword=''):
    """
    记录用户的行为动作，这些数据会被推荐算法用来计算"为你推荐"
    :param action_type: 行为类型，比如 view(浏览), buy(购买), search(搜索)
    :param score: 行为权重分，比如买一次记5分，看一次记1分，分数越高说明越喜欢
    """
    if not user_id:
        return  # 没登录的用户不记录行为（或者视业务需求记录IP）
    
    # 将行为插入 user_actions 表
    execute(
        "INSERT INTO user_actions(user_id, product_id, keyword, action_type, score) VALUES(%s,%s,%s,%s,%s)",
        (user_id, product_id, keyword, action_type, score)
    )

# ================= 7. 获取购物车数据组装 =================
def get_cart_items(user_id):
    """
    查询某个用户的购物车里都有啥，并算出总价
    """
    # 这是一个非常标准的多表联查 (JOIN)：
    # cart_items (购物车表) 连接 products (商品表) 连接 categories (分类表) 连接 users (卖家用户表)
    items = query_all("""
        SELECT ci.id AS cart_id, ci.quantity, ci.created_at AS cart_time,
               p.*, c.name AS category_name, u.username AS seller_name,
               (p.price * ci.quantity) AS subtotal  # 在SQL里直接算出单件商品的小计金额
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE ci.user_id=%s
        ORDER BY ci.created_at DESC  # 最晚加入购物车的排在最前面
    """, (user_id,))
    
    # 【重点语法】：算总价
    # 为什么用 Decimal？因为浮点数算钱会出现 0.1+0.2=0.30000000000000004 的精度丢失问题。
    # Decimal(str(...)) 把金额转成字符串再转成高精度十进制，确保一分钱都不算错。
    total = sum(Decimal(str(i['subtotal'])) for i in items)
    
    return items, total  # 返回商品列表和总价


# ================= 8. 生成唯一订单号 =================
def make_order_no():
    """
    生成一个绝对不会重复的订单号
    格式:20231025143000 (年月日时分秒) + 8位随机大写字母数字
    """
    # datetime.now().strftime('%Y%m%d%H%M%S') 算出当前时间，精确到秒
    # uuid.uuid4().hex[:8].upper() 随机截取8位字符并大写，防止同一秒内两人下单导致订单号重复
    return datetime.now().strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:8].upper()


# ================= 9. 上下文处理器 (前后端连结的桥梁!) =================
# @app.context_processor 是 Flask 的高级魔法：
# 在这里 return 的字典，里面的变量会自动注入到【所有】HTML 模板里，不需要在每个路由里手动传！
@app.context_processor
def inject_common():
    user = current_user()  # 获取当前登录用户
    
    # 获取所有商品分类（用于 base.html 侧边栏展示）
    categories = query_all("SELECT * FROM categories ORDER BY id ASC")
    
    # 获取热卖榜商品（用于 base.html 右侧边栏展示）
    # 热卖公式：(销量 * 3 + 浏览量)。买一次算3分，看一次算1分，分数最高的排前面，取前8名
    hot_products = query_all("""
        SELECT p.*, c.name AS category_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.status='active'  # 只取上架中的商品
        ORDER BY (p.buy_count * 3 + p.view_count) DESC, p.created_at DESC
        LIMIT 8
    """)
    
    cart_count = 0
    order_count = 0
    if user:  # 如果用户登录了
        # COALESCE(SUM(quantity),0) 是一个 SQL 技巧：如果购物车是空的，SUM会返回NULL，COALESCE把NULL变成0
        cart_count = query_one("SELECT COALESCE(SUM(quantity),0) AS n FROM cart_items WHERE user_id=%s", (user['id'],))['n']
        # 查一下该用户有多少笔订单
        order_count = query_one("SELECT COUNT(*) AS n FROM orders WHERE user_id=%s", (user['id'],))['n']
    
    # 把这些变量全部扔给前端模板！
    # 这就是为什么我们在 base.html 里能直接写 {{ current_user }}、{{ categories }}、{{ cart_count }} 的原因！
    return dict(current_user=user, categories=categories, hot_products=hot_products,
                cart_count=cart_count, order_count=order_count, site_name='田禾优选')


# ================= 10. 商城首页 (支持搜索、分类过滤、推荐) =================
@app.route('/')
def index():
    # request.args.get 用于获取 URL 里的参数（GET请求），比如 /?keyword=苹果
    keyword = request.args.get('keyword', '').strip() # .strip() 去除首尾空格
    category_id = request.args.get('category_id', type=int) # 转成整型
    user = current_user()

    # 【重点技巧】：动态构建 SQL 查询条件
    where = ["p.status='active'"] # 基础条件：只查上架的商品
    args = [] # 用于存放 SQL 的参数，防止 SQL 注入
    page_title = '全部商品'

    # --- 处理搜索逻辑 ---
    if keyword:
        # 用户搜了东西，追加搜索条件：名称、描述、产地任意一个匹配即可
        where.append("(p.name LIKE %s OR p.description LIKE %s OR p.origin LIKE %s)")
        like = f"%{keyword}%" # 模糊查询的固定写法，% 代表任意字符
        args.extend([like, like, like])
        page_title = f'搜索：{keyword}'
        if user:
            # 如果登录了，把搜索词存入搜索历史表，并记录行为给推荐系统
            execute("INSERT INTO search_history(user_id, keyword) VALUES(%s,%s)", (user['id'], keyword))
            log_action(user['id'], None, 'search', 1.2, keyword) # 搜索权重给 1.2

    # --- 处理分类过滤逻辑 ---
    if category_id:
        where.append("p.category_id=%s")
        args.append(category_id)
        cat = query_one("SELECT * FROM categories WHERE id=%s", (category_id,))
        if cat:
            page_title = cat['name'] # 页面标题变成分类名，比如"新鲜水果"

    # 执行联表查询，把条件用 AND 拼起来
    products = query_all(f"""
        SELECT p.*, c.name AS category_name, u.username AS seller_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE {' AND '.join(where)}
        ORDER BY p.created_at DESC
    """, tuple(args)) # 记得把 list 转成 tuple 传给数据库

    # 获取推荐商品（调用 recommender.py 里的算法）
    recommended_products = get_recommendations(user['id'] if user else None, limit=6)
    
    # 渲染模板，把查出来的数据统统塞给前端
    return render_template('index.html', products=products, recommended_products=recommended_products,
                           keyword=keyword, active_category_id=category_id, page_title=page_title)


# ================= 11. 商品详情页 =================
@app.route('/product/<int:product_id>')  # <int:product_id> 是 Flask 的动态路由，只能传数字
def product_detail(product_id):
    # 查商品详情，同时连表查出分类名和卖家名
    product = query_one("""
        SELECT p.*, c.name AS category_name, u.username AS seller_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE p.id=%s AND p.status='active'
    """, (product_id,))
    
    if not product:
        flash('商品不存在或已经下架。', 'warning')
        return redirect(url_for('index'))

    # 【重点】：浏览量 +1。每次访问这个页面，数据库里该商品的 view_count 就加 1
    execute("UPDATE products SET view_count=view_count+1 WHERE id=%s", (product_id,))
    
    is_fav = None  # 默认未收藏
    if session.get('user_id'):
        # 如果登录了，记录浏览行为给推荐系统，权重 1.0
        log_action(session['user_id'], product_id, 'view', 1.0)
        # 查一下这个商品用户是不是已经收藏了，用于前端按钮显示“收藏”还是“取消收藏”
        is_fav = query_one("SELECT id FROM favorites WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
        
    return render_template('product_detail.html', product=product, is_fav=is_fav)


# ================= 12. 加入购物车 (核心交易逻辑) =================
@app.route('/product/<int:product_id>/buy', methods=['POST'])  # 必须是 POST 请求
@login_required  # 【老朋友】：必须登录才能买
def add_to_cart(product_id):
    # 1. 查商品存不存在，防过期防下架
    product = query_one("SELECT * FROM products WHERE id=%s AND status='active'", (product_id,))
    if not product:
        flash('商品不存在或已经下架。', 'warning')
        return redirect(url_for('index'))
        
    # 2. 查库存，没货了不能买
    if int(product['stock']) <= 0:
        flash('该商品暂时缺货。', 'warning')
        return redirect(url_for('product_detail', product_id=product_id))

    # 3. 查购物车现状，判断加上现有的数量会不会超过库存
    current = query_one("SELECT quantity FROM cart_items WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    if current and int(current['quantity']) >= int(product['stock']):
        flash('购物车数量已经达到当前库存。', 'warning')
        return redirect(url_for('cart'))

    # 4. 【重点】：数据库事务操作！
    conn = get_db()  # 手动获取数据库连接
    try:
        with conn.cursor() as cursor:
            # 神级 SQL 语法：ON DUPLICATE KEY UPDATE
            # 前提是数据库表里 user_id 和 product_id 建了联合唯一索引。
            # 意思是：如果购物车里没这个商品就 INSERT，如果有就 UPDATE 数量 +1。一句话搞定，不用先查再判断
            cursor.execute("""
                INSERT INTO cart_items(user_id, product_id, quantity)
                VALUES(%s,%s,1)
                ON DUPLICATE KEY UPDATE quantity=quantity+1
            """, (session['user_id'], product_id))
            
            # 记录加入购物车的行为，权重给到 4.0（说明有强烈的购买意向）
            cursor.execute("INSERT INTO user_actions(user_id, product_id, action_type, score) VALUES(%s,%s,'cart',4.0)", (session['user_id'], product_id))
            
            conn.commit()  # 提交事务，两步同时成功
        flash('商品已加入购物车。', 'success')
    except Exception:
        conn.rollback()  # 【重点】：如果上面任何一步报错，回滚事务！数据恢复原样，防止出现脏数据
        flash('加入购物车失败，请稍后重试。', 'danger')
    finally:
        conn.close()  # 无论成功失败，最后必须关闭数据库连接，防止连接泄露
        
    return redirect(url_for('cart'))


# ================= 13. 购物车列表页 =================
@app.route('/cart')
@login_required  # 必须登录
def cart():
    # 调用之前写好的 get_cart_items 函数，拿到购物车商品和总价
    items, total = get_cart_items(session['user_id'])
    return render_template('cart.html', items=items, total=total)


# ================= 14. 购物车单品详情 =================
@app.route('/cart/product/<int:product_id>')
@login_required
def cart_detail(product_id):
    # 查询购物车里某一件指定商品的具体信息（多表联查）
    item = query_one("""
        SELECT ci.id AS cart_id, ci.quantity, p.*, c.name AS category_name, u.username AS seller_name,
               (p.price * ci.quantity) AS subtotal
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE ci.user_id=%s AND p.id=%s
    """, (session['user_id'], product_id))
    
    if not item:
        flash('购物车中没有该商品。', 'warning')
        return redirect(url_for('cart'))
    return render_template('cart_detail.html', item=item)


# ================= 15. 修改购物车数量 =================
@app.route('/cart/product/<int:product_id>/quantity', methods=['POST'])
@login_required
def update_cart_quantity(product_id):
    # 获取前端传来的新数量，如果没有默认给 1
    quantity = request.form.get('quantity', type=int) or 1
    # 查出该商品的最大库存
    product = query_one("SELECT stock FROM products WHERE id=%s", (product_id,))
    if not product:
        flash('商品不存在。', 'warning')
        return redirect(url_for('cart'))
    
    # 【重点语法】：Python 的 min/max 防御性编程
    # min(quantity, stock)：保证数量不能超过库存
    # max(1, ...)：保证数量最少是 1，不能买 0 件或负数件
    quantity = max(1, min(quantity, int(product['stock'])))
    
    # 更新数据库里的数量
    execute("UPDATE cart_items SET quantity=%s WHERE user_id=%s AND product_id=%s", (quantity, session['user_id'], product_id))
    flash('购物车数量已更新。', 'success')
    return redirect(url_for('cart'))


# ================= 16. 移除购物车商品 =================
@app.route('/cart/product/<int:product_id>/remove', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    # 简单粗暴，直接 DELETE
    execute("DELETE FROM cart_items WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    flash('已从购物车移除。', 'success')
    return redirect(url_for('cart'))


# ================= 17. 结算与提交订单 (全项目最硬核逻辑!) =================
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    # 先拿购物车数据
    items, total = get_cart_items(session['user_id'])
    if not items:
        flash('购物车为空，无法提交订单。', 'warning')
        return redirect(url_for('cart'))

    user = current_user()
    
    # --- 如果是 GET 请求：渲染结算页面，把商品和用户信息传给前端填表 ---
    if request.method == 'GET':
        return render_template('checkout.html', items=items, total=total, user=user)

    # --- 如果是 POST 请求：用户点了“提交订单”，开始核心处理 ---
    # 获取收货信息
    receiver_name = request.form.get('receiver_name', '').strip() or user['username']
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    remark = request.form.get('remark', '').strip()

    # 校验必填项和手机号格式（用到了开头的正则）
    if not phone or not address:
        flash('请填写联系电话和收货地址。', 'warning')
        return redirect(url_for('checkout'))
    if not PHONE_RE.match(phone):
        flash('联系电话格式不正确。', 'warning')
        return redirect(url_for('checkout'))

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # 【超级重点】：悲观锁 FOR UPDATE
            # 查购物车商品时加上 FOR UPDATE，会把这些商品行“锁住”。
            # 如果在这一瞬间有别人也在买同样的商品，他们必须等我们这单提交完（锁释放）才能继续。
            # 这是为了防止“超卖”（比如只剩1件货，两人同时下单，结果系统判了两次都对）
            cursor.execute("""
                SELECT ci.product_id, ci.quantity, p.seller_id, p.name, p.image, p.price, p.stock, p.status, c.name AS category_name
                FROM cart_items ci
                JOIN products p ON ci.product_id=p.id
                JOIN categories c ON p.category_id=c.id
                WHERE ci.user_id=%s
                FOR UPDATE
            """, (session['user_id'],))
            locked_items = cursor.fetchall()
            if not locked_items:
                raise ValueError('购物车为空。')

            # 重新计算总价，并再次校验库存和状态（防止在结账这几秒内商品下架了）
            order_total = Decimal('0.00')
            for item in locked_items:
                if item['status'] != 'active':
                    raise ValueError(f"{item['name']} 已下架，不能提交订单。")
                if int(item['stock']) < int(item['quantity']):
                    raise ValueError(f"{item['name']} 库存不足。")
                order_total += Decimal(str(item['price'])) * int(item['quantity'])

            # 1. 生成订单号，插入 orders 主表
            order_no = make_order_no()
            cursor.execute("""
                INSERT INTO orders(order_no, user_id, total_amount, receiver_name, phone, address, remark)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
            """, (order_no, session['user_id'], order_total, receiver_name, phone, address, remark))
            order_id = cursor.lastrowid  # 获取刚生成的订单 ID

            # 2. 遍历购物车商品，插入 order_items 订单明细表
            for item in locked_items:
                subtotal = Decimal(str(item['price'])) * int(item['quantity'])
                cursor.execute("""
                    INSERT INTO order_items(order_id, product_id, seller_id, product_name, product_image, category_name, price, quantity, subtotal)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (order_id, item['product_id'], item['seller_id'], item['name'], item['image'], item['category_name'], item['price'], item['quantity'], subtotal))
                
                # 3. 扣库存，加销量！
                cursor.execute("UPDATE products SET stock=stock-%s, buy_count=buy_count+%s WHERE id=%s", (item['quantity'], item['quantity'], item['product_id']))
                
                # 4. 记录购买流水（给个人中心的“购买记录”用）
                cursor.execute("INSERT INTO purchase_records(user_id, product_id, order_id) VALUES(%s,%s,%s)", (session['user_id'], item['product_id'], order_id))
                
                # 5. 记录行为日志（购买行为权重给到最高 5.0，强力喂给推荐系统）
                cursor.execute("INSERT INTO user_actions(user_id, product_id, action_type, score) VALUES(%s,%s,'order',5.0)", (session['user_id'], item['product_id']))

            # 6. 清空当前用户的购物车
            cursor.execute("DELETE FROM cart_items WHERE user_id=%s", (session['user_id'],))
            
            conn.commit()  # 提交事务！所有操作一起生效，锁释放。
            
        flash('订单提交成功。', 'success')
        # 跳转到该订单的详情页
        return redirect(url_for('order_detail', order_id=order_id))
    
    # 捕获库存不足、下架等业务逻辑错误
    except ValueError as e:
        conn.rollback()  # 回滚，不扣库存，不生成订单
        flash(str(e), 'warning')
        return redirect(url_for('cart'))
    # 捕获数据库断开等未知系统错误
    except Exception:
        conn.rollback()
        flash('订单提交失败，请稍后重试。', 'danger')
        return redirect(url_for('cart'))
    finally:
        conn.close()  # 坚决关闭连接


# ================= 18. 我的订单列表 =================
@app.route('/orders')
@login_required
def orders():
    # 查询当前用户的所有订单
    rows = query_all("""
        SELECT o.*,
               # 【重点语法】：SQL 子查询。在查订单的同时，顺手统计出这笔订单里买了几种商品
               (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id=o.id) AS item_count
        FROM orders o
        WHERE o.user_id=%s
        ORDER BY o.created_at DESC
    """, (session['user_id'],))
    return render_template('orders.html', orders=rows)


# ================= 19. 订单详情 =================
@app.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    user = current_user()
    order = query_one("SELECT * FROM orders WHERE id=%s", (order_id,))
    
    # 【重点】：越权访问防御！
    # 如果订单不存在，或者（订单不是你的 且 你不是管理员），直接拦截。
    # 防止用户通过随便猜网址（比如 /orders/1）偷看别人的订单
    if not order or (order['user_id'] != user['id'] and user['role'] != 'admin'):
        flash('订单不存在或无权查看。', 'warning')
        return redirect(url_for('orders'))
        
    # 查出这笔订单里的所有商品明细
    items = query_all("SELECT * FROM order_items WHERE order_id=%s ORDER BY id ASC", (order_id,))
    return render_template('order_detail.html', order=order, items=items)


# ================= 20. 取消订单 (含库存恢复) =================
@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    # 查订单，且必须查自己的订单
    order = query_one("SELECT * FROM orders WHERE id=%s AND user_id=%s", (order_id, session['user_id']))
    if not order:
        flash('订单不存在。', 'warning')
        return redirect(url_for('orders'))
        
    # 状态机校验：只有“待处理”的订单才能取消，已发货的不能取消
    if order['status'] != '待处理':
        flash('只有待处理订单可以取消。', 'warning')
        return redirect(url_for('order_detail', order_id=order_id))

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            # 查出这笔订单里都有哪些商品和对应的数量
            cursor.execute("SELECT product_id, quantity FROM order_items WHERE order_id=%s", (order_id,))
            items = cursor.fetchall()
            
            # 遍历商品，把扣掉的库存加回去
            for item in items:
                if item['product_id']:
                    # 【重点语法】：GREATEST(buy_count-%s, 0)
                    # 意思是：销量减去取消的数量，但如果减完是负数，就取 0。
                    # 这是为了防止极端情况（比如管理员手动改过销量）导致销量变成负数报错
                    cursor.execute("UPDATE products SET stock=stock+%s, buy_count=GREATEST(buy_count-%s, 0) WHERE id=%s", (item['quantity'], item['quantity'], item['product_id']))
            
            # 订单状态改为“已取消”
            cursor.execute("UPDATE orders SET status='已取消' WHERE id=%s", (order_id,))
            conn.commit()
        flash('订单已取消。', 'success')
    except Exception:
        conn.rollback()  # 恢复库存和取消订单必须同时成功，否则回滚
        flash('取消订单失败。', 'danger')
    finally:
        conn.close()
    return redirect(url_for('order_detail', order_id=order_id))


# ================= 21. 确认收货 =================
@app.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm_order(order_id):
    order = query_one("SELECT * FROM orders WHERE id=%s AND user_id=%s", (order_id, session['user_id']))
    if not order:
        flash('订单不存在。', 'warning')
        return redirect(url_for('orders'))
        
    # 状态机校验：只有“已发货”的才能确认收货
    if order['status'] != '已发货':
        flash('只有已发货订单可以确认收货。', 'warning')
        return redirect(url_for('order_detail', order_id=order_id))
        
    # 简单更新状态即可，不涉及库存变动
    execute("UPDATE orders SET status='已完成' WHERE id=%s", (order_id,))
    flash('已确认收货，订单完成。', 'success')
    return redirect(url_for('order_detail', order_id=order_id))


# ================= 22. 收藏/取消收藏 (一鱼两吃) =================
@app.route('/favorite/<int:product_id>', methods=['POST'])
@login_required
def toggle_favorite(product_id):
    # 查一下是不是已经收藏过了
    exists = query_one("SELECT id FROM favorites WHERE user_id=%s AND product_id=%s", (session['user_id'], product_id))
    if exists:
        # 收藏过 -> 删除收藏
        execute("DELETE FROM favorites WHERE id=%s", (exists['id'],))
        flash('已取消关注。', 'success')
    else:
        # 没收藏 -> 新增收藏，并记录行为给推荐系统（权重 3.0）
        execute("INSERT INTO favorites(user_id, product_id) VALUES(%s,%s)", (session['user_id'], product_id))
        log_action(session['user_id'], product_id, 'favorite', 3.0)
        flash('已加入我的关注。', 'success')
        
    # 【重点语法】：request.referrer
    # 意思是：返回用户发起请求的上一页。
    # 因为用户可能在首页点收藏，也可能在详情页点收藏，用这个就能智能返回原页面，体验极佳！
    # 如果获取不到上一页（比如直接输网址访问），就兜底跳到详情页
    return redirect(request.referrer or url_for('product_detail', product_id=product_id))


# ================= 23. 我的关注列表 =================
@app.route('/favorites')
@login_required
def favorites():
    # 多表联查用户的收藏夹，顺便过滤掉已经被卖家下架的商品
    products = query_all("""
        SELECT f.created_at AS fav_time, p.*, c.name AS category_name, u.username AS seller_name
        FROM favorites f
        JOIN products p ON f.product_id = p.id
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE f.user_id=%s AND p.status='active'
        ORDER BY f.created_at DESC
    """, (session['user_id'],))
    return render_template('favorites.html', products=products)


# ================= 24. 卖货中心 (发布商品 + 查看自己的商品和订单) =================
@app.route('/sell', methods=['GET', 'POST'])
@login_required  # 必须登录
def sell():
    # --- POST 请求：处理用户提交的发布商品表单 ---
    if request.method == 'POST':
        # 接收前端表单数据，strip() 去空格，type=int/float 强转类型
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int)
        price = request.form.get('price', type=float)
        stock = request.form.get('stock', type=int) or 1  # 如果没填库存，默认给 1
        origin = request.form.get('origin', '').strip()
        description = request.form.get('description', '').strip()
        # 获取上传的图片文件对象
        image_file = request.files.get('image')

        # 服务端二次校验：防止前端绕过校验瞎传数据
        if not name or not category_id or price is None or price < 0:
            flash('请完整填写商品名称、类别和价格。', 'warning')
            return redirect(url_for('sell'))
        if stock < 1:
            flash('库存数量至少为 1。', 'warning')
            return redirect(url_for('sell'))

        try:
            # 调用我们之前看过的工具函数保存图片，返回相对路径
            image_path = save_uploaded_image(image_file)
        except ValueError as e:
            # 如果图片格式不对，工具函数会抛异常，这里接住并提示用户
            flash(str(e), 'warning')
            return redirect(url_for('sell'))

        # 数据没问题了，插入 products 表
        execute("""
            INSERT INTO products(seller_id, category_id, name, image, price, stock, origin, description)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        """, (session['user_id'], category_id, name, image_path, price, stock, origin, description))
        flash('商品发布成功，已进入商品列表。', 'success')
        return redirect(url_for('sell'))

    # --- GET 请求：渲染卖家中心页面 ---
    # 1. 查出当前用户发布的所有商品，并统计每件商品卖了多少单（子查询）
    my_products = query_all("""
        SELECT p.*, c.name AS category_name,
               (SELECT COUNT(*) FROM order_items oi WHERE oi.product_id=p.id) AS order_count
        FROM products p JOIN categories c ON p.category_id=c.id
        WHERE p.seller_id=%s ORDER BY p.created_at DESC
    """, (session['user_id'],))
    
    # 2. 查出当前卖家最近 12 条售出记录（多表联查订单明细和订单主表）
    seller_orders = query_all("""
        SELECT oi.*, o.order_no, o.status, o.created_at, o.receiver_name, o.phone, o.address
        FROM order_items oi
        JOIN orders o ON oi.order_id=o.id
        WHERE oi.seller_id=%s
        ORDER BY o.created_at DESC LIMIT 12
    """, (session['user_id'],))
    
    return render_template('sell.html', my_products=my_products, seller_orders=seller_orders)


# ================= 25. 编辑商品 =================
@app.route('/seller/product/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    # 【重点】：归属权校验！查询商品时必须带上 seller_id=%s。
    # 这样可以防止卖家 A 通过猜网址（比如 /seller/product/2/edit）去编辑卖家 B 的商品
    product = query_one("SELECT * FROM products WHERE id=%s AND seller_id=%s", (product_id, session['user_id']))
    if not product:
        flash('商品不存在或无权编辑。', 'warning')
        return redirect(url_for('sell'))

    # --- POST 请求：保存修改 ---
    if request.method == 'POST':
        # 接收数据...（和发布商品逻辑类似）
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int)
        price = request.form.get('price', type=float)
        stock = request.form.get('stock', type=int) or 1
        origin = request.form.get('origin', '').strip()
        description = request.form.get('description', '').strip()
        image_file = request.files.get('image')
        
        if not name or not category_id or price is None or price < 0 or stock < 0:
            flash('请正确填写商品信息。', 'warning')
            return redirect(url_for('edit_product', product_id=product_id))
            
        try:
            # 【重点】：传入 old_path。如果用户没传新图，就保留原图片路径，防止图片丢失
            image_path = save_uploaded_image(image_file, old_path=product['image'])
        except ValueError as e:
            flash(str(e), 'warning')
            return redirect(url_for('edit_product', product_id=product_id))
            
        # 执行更新操作。注意 WHERE 条件里同样带了 seller_id 防越权
        execute("""
            UPDATE products SET category_id=%s, name=%s, image=%s, price=%s, stock=%s, origin=%s, description=%s
            WHERE id=%s AND seller_id=%s
        """, (category_id, name, image_path, price, stock, origin, description, product_id, session['user_id']))
        flash('商品信息已保存。', 'success')
        return redirect(url_for('sell'))

    # --- GET 请求：渲染编辑页面，把原商品信息传给前端做表单回填 ---
    return render_template('edit_product.html', product=product)


# ================= 26. 上下架切换 =================
@app.route('/seller/product/<int:product_id>/toggle', methods=['POST'])
@login_required
def seller_toggle_product(product_id):
    # 查出当前商品状态（带归属权校验）
    product = query_one("SELECT status FROM products WHERE id=%s AND seller_id=%s", (product_id, session['user_id']))
    if not product:
        flash('商品不存在或无权操作。', 'warning')
        return redirect(url_for('sell'))
        
    # 【Python 语法】：三元运算符。如果是 active 就变成 off，否则变成 active
    new_status = 'off' if product['status'] == 'active' else 'active'
    execute("UPDATE products SET status=%s WHERE id=%s AND seller_id=%s", (new_status, product_id, session['user_id']))
    flash('商品状态已更新。', 'success')
    return redirect(url_for('sell'))


# ================= 27. 删除商品 =================
@app.route('/seller/product/<int:product_id>/delete', methods=['POST'])
@login_required
def seller_delete_product(product_id):
    # 直接执行 DELETE，但 WHERE 条件里必须带 seller_id。
    # 如果不带，黑客就能通过发请求删掉别人的商品（俗称越权删除）
    execute("DELETE FROM products WHERE id=%s AND seller_id=%s", (product_id, session['user_id']))
    flash('商品已删除。', 'success')
    return redirect(url_for('sell'))


# ================= 28. 用户登录 =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # 根据用户名去数据库查用户
        user = query_one("SELECT * FROM users WHERE username=%s", (username,))
        
        # 【重点安全逻辑】：密码校验
        # 1. not user：用户名不存在
        # 2. not check_password_hash(...)：用户名存在，但密码不对。
        #    数据库里存的是哈希加密后的密文，不能用 == 直接对比，必须用 check_password_hash 函数解密对比。
        # 注意：报错信息统一写“用户名或密码错误”，绝对不能写“用户名不存在”。
        # 因为如果写“用户名不存在”，黑客就能用这个接口探测出哪些手机号/用户名注册过，这叫防用户枚举攻击。
        if not user or not check_password_hash(user['password_hash'], password):
            flash('用户名或密码错误。', 'danger')
            return redirect(url_for('login'))
            
        # 验证通过，把用户的 id 存入 session（相当于发一张通行证，以后各处都能认出他）
        session['user_id'] = user['id']
        flash(f'欢迎回来，{user["username"]}。', 'success')
        return redirect(url_for('index'))
        
    # GET 请求：渲染登录页面
    return render_template('login.html')


# ================= 29. 用户注册 =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')

        # 服务端正则二次校验（防前端绕过）
        if not USERNAME_RE.match(username):
            flash('用户名需为 1-10 位汉字、大小写字母或数字。', 'warning')
            return redirect(url_for('register'))
        if not PASSWORD_RE.match(password):
            flash('密码需为 8-18 位，并同时包含大写字母、小写字母和数字。', 'warning')
            return redirect(url_for('register'))
        if password != confirm:
            flash('两次输入的密码不一致。', 'warning')
            return redirect(url_for('register'))
            
        # 查重：确保用户名没被注册过
        if query_one("SELECT id FROM users WHERE username=%s", (username,)):
            flash('该用户名已经存在。', 'warning')
            return redirect(url_for('register'))

        # 【重点安全逻辑】：密码加密
        # 绝对不能明文存密码！generate_password_hash 会把密码变成一串无法被反向破解的乱码存入数据库。
        # 哪怕数据库泄露了，黑客也拿不到用户的真实密码。
        uid = execute(
            "INSERT INTO users(username, password_hash, role) VALUES(%s,%s,'user')",
            (username, generate_password_hash(password))
        )
        
        session['user_id'] = uid  # 注册完直接发通行证，实现“注册并自动登录”
        flash('注册成功，已自动登录。', 'success')
        return redirect(url_for('index'))
        
    return render_template('register.html')


# ================= 30. 退出登录 =================
@app.route('/logout')
def logout():
    session.clear()  # 清除浏览器 session 里的所有数据（主要是 user_id），通行证作废
    flash('已退出登录。', 'success')
    return redirect(url_for('index'))


# ================= 31. 个人中心 =================
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # --- POST 请求：修改性别、电话、地址 ---
    if request.method == 'POST':
        gender = request.form.get('gender', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        execute("UPDATE users SET gender=%s, phone=%s, address=%s WHERE id=%s", (gender, phone, address, session['user_id']))
        flash('个人信息已更新。', 'success')
        return redirect(url_for('profile'))

    # --- GET 请求：聚合查询个人中心的四大板块数据 ---
    user = current_user()
    
    # 1. 查我上传的商品（关联分类表）
    uploads = query_all("""
        SELECT p.*, c.name AS category_name
        FROM products p JOIN categories c ON p.category_id=c.id
        WHERE p.seller_id=%s ORDER BY p.created_at DESC
    """, (session['user_id'],))
    
    # 2. 查我的购买记录（关联流水表、商品表、分类表）
    # 用了 LEFT JOIN 左连接：就算商品被卖家删了，购买流水依然在，只是商品信息为 NULL
    purchases = query_all("""
        SELECT pr.created_at, pr.order_id, p.name, p.price, p.image, c.name AS category_name
        FROM purchase_records pr
        LEFT JOIN products p ON pr.product_id=p.id
        LEFT JOIN categories c ON p.category_id=c.id
        WHERE pr.user_id=%s ORDER BY pr.created_at DESC LIMIT 12
    """, (session['user_id'],))
    
    # 3. 查我的搜索历史（最近 12 条）
    searches = query_all("SELECT * FROM search_history WHERE user_id=%s ORDER BY created_at DESC LIMIT 12", (session['user_id'],))
    
    # 把数据统统塞给前端
    return render_template('profile.html', user=user, uploads=uploads, purchases=purchases, searches=searches)


# ================= 32. 后台管理仪表盘 =================
@app.route('/admin')
@admin_required  # 【老朋友】：管理员专属装饰器
def admin_dashboard():
    # 【重点】：数据大屏的统计逻辑
    # COUNT(*) 数表里有几行记录
    stats = {
        'users': query_one("SELECT COUNT(*) AS n FROM users")['n'],
        'products': query_one("SELECT COUNT(*) AS n FROM products")['n'],
        'orders': query_one("SELECT COUNT(*) AS n FROM orders")['n'],
        'actions': query_one("SELECT COUNT(*) AS n FROM user_actions")['n'],
        # COALESCE(SUM(total_amount),0) 算总营业额。
        # WHERE status<>'已取消'：取消的订单不算进总营业额里，逻辑非常严谨
        'sales': query_one("SELECT COALESCE(SUM(total_amount),0) AS n FROM orders WHERE status<>'已取消'")['n'],
    }
    
    # 查最新的 8 件商品
    recent_products = query_all("""
        SELECT p.*, c.name AS category_name, u.username AS seller_name
        FROM products p JOIN categories c ON p.category_id=c.id JOIN users u ON p.seller_id=u.id
        ORDER BY p.created_at DESC LIMIT 8
    """)
    
    # 查最新的 8 笔订单
    recent_orders = query_all("""
        SELECT o.*, u.username
        FROM orders o JOIN users u ON o.user_id=u.id
        ORDER BY o.created_at DESC LIMIT 8
    """)
    
    return render_template('admin_dashboard.html', stats=stats, recent_products=recent_products, recent_orders=recent_orders)

# ================= 33. 后台商品管理列表 =================
@app.route('/admin/products')
@admin_required  # 【老朋友】：管理员专属
def admin_products():
    # 查出全平台所有商品（不带 seller_id 限制，因为管理员能看所有的）
    products = query_all("""
        SELECT p.*, c.name AS category_name, u.username AS seller_name
        FROM products p JOIN categories c ON p.category_id=c.id JOIN users u ON p.seller_id=u.id
        ORDER BY p.created_at DESC
    """)
    return render_template('admin_products.html', products=products)


# ================= 34. 管理员强制上下架商品 =================
@app.route('/admin/product/<int:product_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_product(product_id):
    # 查出商品状态（注意这里没有带 seller_id 校验，管理员有权管任何人的商品）
    product = query_one("SELECT status FROM products WHERE id=%s", (product_id,))
    if product:
        # 切换状态并更新
        new_status = 'off' if product['status'] == 'active' else 'active'
        execute("UPDATE products SET status=%s WHERE id=%s", (new_status, product_id))
        flash('商品状态已更新。', 'success')
    return redirect(url_for('admin_products'))


# ================= 35. 管理员强制删除商品 =================
@app.route('/admin/product/<int:product_id>/delete', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    # 直接删除（同样不需要校验卖家身份）
    execute("DELETE FROM products WHERE id=%s", (product_id,))
    flash('商品已删除。', 'success')
    return redirect(url_for('admin_products'))


# ================= 36. 后台订单管理列表 =================
@app.route('/admin/orders')
@admin_required
def admin_orders():
    # 查出全平台所有订单，并用子查询统计每笔订单的商品种类数
    rows = query_all("""
        SELECT o.*, u.username,
               (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id=o.id) AS item_count
        FROM orders o JOIN users u ON o.user_id=u.id
        ORDER BY o.created_at DESC
    """)
    return render_template('admin_orders.html', orders=rows)


# ================= 37. 管理员修改订单状态 =================
@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@admin_required
def admin_update_order_status(order_id):
    status = request.form.get('status')
    
    # 【重点安全逻辑】：状态白名单校验！
    # 管理员前端虽然是用下拉框传的值，但黑客可以抓包把 status 改成任意奇葩字符串（比如 "被黑客攻击"）。
    # 这行代码确保：传进来的状态只能是这 4 个合法的中文词汇之一，否则拒绝写入数据库。
    if status not in ['待处理', '已发货', '已完成', '已取消']:
        flash('订单状态不正确。', 'warning')
        return redirect(url_for('admin_orders'))
        
    execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))
    flash('订单状态已更新。', 'success')
    return redirect(url_for('admin_orders'))


# ================= 38. 后台用户管理列表 =================
@app.route('/admin/users')
@admin_required
def admin_users():
    # 查出所有用户，并用子查询分别统计每个用户上传了多少商品、下了多少单
    users = query_all("""
        SELECT u.*,
               (SELECT COUNT(*) FROM products p WHERE p.seller_id=u.id) AS product_count,
               (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS order_count
        FROM users u ORDER BY u.created_at DESC
    """)
    return render_template('admin_users.html', users=users)


# ================= 39. 全局 404 错误处理 =================
# @app.errorhandler(404) 会拦截整个项目中所有的 "404 Not Found" 报错。
# 比如用户乱敲了一个不存在的网址，不再显示 Flask 默认的丑陋英文报错页，而是渲染你写好的 404.html 模板。
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404  # 后面的 404 是 HTTP 状态码，告诉浏览器这确实是个 404 页面


# ================= 40. 程序启动入口 =================
if __name__ == '__main__':
    # 只有当你直接运行 python app.py 时，这里的代码才会执行。
    # host='0.0.0.0'：允许局域网内的其他设备（比如你的手机）通过你的电脑 IP 访问这个网站。
    # port=5000：监听 5000 端口。
    # debug=True：开启调试模式。如果你修改了代码，Flask 会自动重启服务；如果网页报错，会在浏览器上显示详细的报错堆栈（极其方便开发，但上线时必须改为 False）。
    app.run(host='0.0.0.0', port=5000, debug=True)
