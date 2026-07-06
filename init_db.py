from werkzeug.security import generate_password_hash
from db import get_db


def run_sql_script(cursor, text):
    """执行 SQL 脚本文件里的建表语句"""
    for statement in text.split(';'):
        statement = statement.strip()
        if statement:
            cursor.execute(statement)


def main():
    # 1. 第一次连接：不指定具体数据库，执行 schema.sql 创建数据库和表结构
    conn = get_db(database=False)
    try:
        with conn.cursor() as cursor:
            with open('schema.sql', 'r', encoding='utf-8') as f:
                run_sql_script(cursor, f.read())
            conn.commit()
    finally:
        conn.close()

    # 2. 第二次连接：连入刚创建的 farm_mall 数据库，插入初始化测试数据
    conn = get_db(database=True)
    try:
        with conn.cursor() as cursor:
            # 生成密码哈希密文
            admin_hash = generate_password_hash('Admin123456')
            user_hash = generate_password_hash('User123456')

            # 插入预设的测试账号：一个管理员，一个普通用户
            users = [
                ('admin', admin_hash, 'admin', '保密', '13800000000', '陕西省西安市雁塔区'),
                ('小农户', user_hash, 'user', '男', '13900000000', '陕西省西安市长安区'),
            ]
            for u in users:
                cursor.execute(
                    "INSERT INTO users(username, password_hash, role, gender, phone, address) VALUES(%s,%s,%s,%s,%s,%s)",
                    u
                )

            # 插入商品分类数据
            categories = [
                ('时令水果', '5,6,7,8,9,10'),
                ('新鲜蔬菜', '3,4,5,6,7,8,9,10'),
                ('粮油米面', '1,2,3,4,5,6,7,8,9,10,11,12'),
                ('禽蛋肉类', '1,2,3,4,5,6,7,8,9,10,11,12'),
                ('农副干货', '9,10,11,12,1,2'),
                ('地方特产', '1,2,3,4,5,6,7,8,9,10,11,12'),
            ]
            for name, months in categories:
                cursor.execute("INSERT INTO categories(name, season_months) VALUES(%s,%s)", (name, months))

            # 插入商品测试数据。
            # seller_id 统一设为 2 (即"小农户"账号)，让所有商品都有明确的归属，避免孤儿数据。
            products = [
                (2, 1, '洛川红富士苹果', 'img/default_product.svg', 8.80, 500, '陕西延安', '果形端正，口感脆甜，产地直发，适合作为家庭日常水果。', 32, 18),
                (2, 1, '周至猕猴桃', 'img/default_product.svg', 6.50, 360, '陕西周至', '酸甜适中，果香浓郁，适合鲜食和礼盒搭配。', 21, 12),
                (2, 2, '秦岭山地菠菜', 'img/default_product.svg', 3.20, 300, '陕西商洛', '当天采摘，叶片鲜嫩，适合家庭日常烹饪。', 18, 9),
                (2, 2, '有机西红柿', 'img/default_product.svg', 5.60, 260, '陕西杨凌', '沙瓤多汁，酸甜平衡，适合凉拌、炒菜和煲汤。', 26, 14),
                (2, 3, '陕北小米', 'img/default_product.svg', 12.90, 420, '陕西榆林', '颗粒饱满，米香自然，熬粥口感细腻。', 41, 25),
                (2, 3, '农家菜籽油', 'img/default_product.svg', 68.00, 120, '陕西汉中', '传统压榨，香味浓郁，适合家庭炒菜。', 36, 20),
                (2, 4, '散养土鸡蛋', 'img/default_product.svg', 18.80, 180, '陕西蓝田', '农户散养，蛋黄饱满，适合早餐和家庭烘焙。', 55, 31),
                (2, 5, '富平柿饼', 'img/default_product.svg', 29.90, 150, '陕西富平', '软糯香甜，霜白自然，适合零食和礼品。', 48, 28),
                (2, 6, '临潼石榴礼盒', 'img/default_product.svg', 39.90, 100, '陕西临潼', '果粒饱满，色泽鲜亮，适合家庭分享。', 39, 17),
                (2, 6, '商洛核桃', 'img/default_product.svg', 25.80, 200, '陕西商洛', '薄皮核桃，果仁饱满，营养丰富。', 34, 19),
                (2, 5, '秦岭黑木耳', 'img/default_product.svg', 32.00, 160, '陕西安康', '肉厚爽脆，泡发率高，适合凉拌和炖汤。', 29, 15),
                (2, 2, '农家嫩黄瓜', 'img/default_product.svg', 4.20, 280, '陕西咸阳', '清脆多汁，适合凉拌、蘸酱和家庭餐桌。', 22, 11),
            ]
            for p in products:
                cursor.execute("""
                    INSERT INTO products(seller_id, category_id, name, image, price, stock, origin, description, view_count, buy_count)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, p)

            # 初始化少量行为数据，便于首页推荐区在演示时更自然。
            # user_id 包含 1 (admin) 和 2 (小农户)，确保推荐系统启动时有数据可以计算。
            actions = [
                (2, 1, 'view', 1.0), (2, 1, 'favorite', 3.0), (2, 5, 'cart', 4.0),
                (2, 7, 'view', 1.0), (1, 8, 'favorite', 3.0), (1, 10, 'cart', 4.0),
                (1, 11, 'view', 1.0), (1, 9, 'view', 1.0),
            ]
            for a in actions:
                cursor.execute("INSERT INTO user_actions(user_id, product_id, action_type, score) VALUES(%s,%s,%s,%s)", a)

            conn.commit()
            
            print('数据库初始化完成。')
            print('管理员账号：admin / Admin123456')
            print('普通用户账号：小农户 / User123456')
    finally:
        conn.close()


if __name__ == '__main__':
    main()