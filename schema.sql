-- ================= 1. 创建数据库与基本设置 =================
-- 如果不存在 farm_mall 数据库，则创建它。指定字符集为 utf8mb4（支持存 Emoji 和生僻字），排序规则为 unicode_ci
CREATE DATABASE IF NOT EXISTS farm_mall DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE farm_mall;  -- 切换到这个数据库

-- ================= 2. 安全重置表 (防报错) =================
-- 暂时关闭外键约束检查。因为如果先删除主表（users），从表（orders）会报错外键依赖，关掉检查就能随意删了
SET FOREIGN_KEY_CHECKS = 0;
-- 按照依赖顺序倒序删除表（如果表存在）。这保证了脚本可以反复运行（幂等性）
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS purchase_records;
DROP TABLE IF EXISTS user_actions;
DROP TABLE IF EXISTS search_history;
DROP TABLE IF EXISTS favorites;
DROP TABLE IF EXISTS cart_items;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;
-- 删完表后，重新开启外键约束检查
SET FOREIGN_KEY_CHECKS = 1;


-- ================= 3. 用户表 (users) =================
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,  -- 自增主键
    username VARCHAR(10) NOT NULL UNIQUE,  -- 用户名，最多10字符，不能重复
    password_hash VARCHAR(255) NOT NULL,  -- 密码哈希值
    role ENUM('user','admin') NOT NULL DEFAULT 'user',  -- 枚举类型：只能是普通用户或管理员
    gender VARCHAR(20) DEFAULT '保密',
    phone VARCHAR(30) DEFAULT '',
    address VARCHAR(255) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- 注册时间，默认当前时间
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;  -- 使用 InnoDB 引擎（支持事务和外键）


-- ================= 4. 分类表 (categories) =================
CREATE TABLE categories (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(50) NOT NULL UNIQUE,  -- 分类名，比如"时令水果"
    season_months VARCHAR(50) DEFAULT '',  -- 上市季节月份，比如 "5,6,7,8"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 5. 商品表 (products) =================
CREATE TABLE products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    seller_id INT NOT NULL,  -- 谁卖的
    category_id INT NOT NULL,  -- 属于哪个分类
    name VARCHAR(100) NOT NULL,
    image VARCHAR(255) NOT NULL DEFAULT 'img/default_product.svg',  -- 默认占位图
    -- 【重点】：DECIMAL(10,2) 专门用来存金额。最长10位数字，其中2位小数。绝对不能用 FLOAT，会有精度丢失
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    stock INT NOT NULL DEFAULT 999,
    origin VARCHAR(100) DEFAULT '',
    description TEXT,  -- 长文本，存商品介绍
    status ENUM('active','off') NOT NULL DEFAULT 'active',  -- 上架或下架
    view_count INT NOT NULL DEFAULT 0,  -- 浏览量
    buy_count INT NOT NULL DEFAULT 0,  -- 销量
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 每次更新这行数据时，自动更新 updated_at 为当前时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- 外键约束：
    -- ON DELETE CASCADE：如果用户被删了，他名下的商品也跟着删
    -- ON DELETE RESTRICT：如果分类下还有商品，禁止删除该分类（防止商品变成孤儿）
    FOREIGN KEY (seller_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 6. 购物车表 (cart_items) =================
CREATE TABLE cart_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 【超级重点】：联合唯一键！
    -- 意思是 user_id 和 product_id 的组合不能重复。
    -- 这就是为什么在 app.py 里敢于使用 "ON DUPLICATE KEY UPDATE quantity=quantity+1" 的底气！
    UNIQUE KEY uk_user_product (user_id, product_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 7. 收藏表 (favorites) =================
CREATE TABLE favorites (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 同样，一个用户对同一件商品只能收藏一次
    UNIQUE KEY uk_fav_user_product (user_id, product_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 8. 搜索历史表 (search_history) =================
CREATE TABLE search_history (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    keyword VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 9. 用户行为日志表 (user_actions) =================
CREATE TABLE user_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    product_id INT NULL,  -- 允许为空。因为搜索动作没有对应的商品
    keyword VARCHAR(100) DEFAULT '',
    action_type VARCHAR(30) NOT NULL,  -- view, cart, favorite, order, search
    score DECIMAL(6,2) NOT NULL DEFAULT 0,  -- 行为权重打分，供推荐系统用
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    -- 注意这里是 ON DELETE CASCADE，如果商品删了，相关的行为日志也删掉
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 10. 订单主表 (orders) =================
CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    order_no VARCHAR(32) NOT NULL UNIQUE,  -- 订单号，唯一
    user_id INT NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL DEFAULT 0,  -- 订单总金额
    receiver_name VARCHAR(50) NOT NULL,  -- 收货人（下单时的快照）
    phone VARCHAR(30) NOT NULL,
    address VARCHAR(255) NOT NULL,
    remark VARCHAR(255) DEFAULT '',
    status ENUM('待处理','已发货','已完成','已取消') NOT NULL DEFAULT '待处理',  -- 状态机
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 11. 订单明细表 (order_items) =================
CREATE TABLE order_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    product_id INT NULL,  -- 【重点】：允许为空！配合下面的 ON DELETE SET NULL
    seller_id INT NULL,
    -- 【重点】：订单快照字段！把买那一刻的商品名字、图片、价格死死记下来
    product_name VARCHAR(100) NOT NULL,
    product_image VARCHAR(255) NOT NULL,
    category_name VARCHAR(50) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    quantity INT NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    -- 【重点设计】：如果卖家把商品删除了，这里只把 product_id 置为空，但订单明细依然保留！
    -- 这就是为什么我们在 profile.html 里看到 "{{ p.name or '商品已删除' }}"，因为商品没了，但订单流水还在
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
    FOREIGN KEY (seller_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ================= 12. 购买流水记录表 (purchase_records) =================
CREATE TABLE purchase_records (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    product_id INT NULL,
    order_id INT NULL,
    action_type VARCHAR(30) NOT NULL DEFAULT 'order',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;