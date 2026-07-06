"""
田禾优选混合推荐模块（修订版）

修订目的：
1. 将“搜索行为”真正纳入推荐计算，而不是只记录搜索历史；
2. 将“季节权重”作为单独的推荐因子，避免在行为权重、热度和最终得分中重复计算；
3. 将协同过滤部分改为更清晰的“物品相似度 + 加权平均”形式；
4. 对各项得分进行归一化，使 0.35、0.25 等权重具有实际意义；

算法定位：
本模块采用基于隐式反馈的轻量级混合推荐算法。系统根据用户的浏览、
搜索、关注、加购等行为构建兴趣画像，并融合物品协同过滤、搜索意图、
类别偏好、商品热度和季节因素，最终对候选商品进行综合排序。

注意：
本文件保持原有接口 get_recommendations(user_id=None, limit=8) 不变，
可以直接替换原系统中的 recommender.py。
"""

import math
from datetime import datetime
from collections import defaultdict
from db import query_all


# =========================
# 1. 参数设置
# =========================

# 行为基础权重。
# 设计依据：按照用户购买意图强弱递增。
# 浏览 < 搜索 < 关注 < 加入购物车 < 已购买/下单
ACTION_WEIGHT = {
    "view": 1.0,       # 浏览：弱兴趣
    "search": 2.0,     # 搜索：用户主动表达需求，强于浏览
    "favorite": 3.0,   # 关注/收藏：持续兴趣
    "cart": 4.0,       # 加入购物车：较强购买意向
    "order": 5.0,      # 下单/购买：最强兴趣信号，兼容可能的行为类型
    "purchase": 5.0,
}

# 最终混合推荐各部分权重。
# 各项之和为 1，便于解释和调参。
# 协同过滤用于挖掘相似商品，搜索意图体现用户当前主动需求，
# 类别偏好反映长期兴趣，热度用于冷启动补充，季节因素体现农产品时令性。
FINAL_WEIGHT = {
    "cf": 0.35,          # 物品协同过滤
    "search": 0.25,      # 搜索意图匹配
    "category": 0.15,    # 类别兴趣
    "popularity": 0.15,  # 商品热度
    "season": 0.10,      # 季节因素
}

# 时间衰减周期。数值越大，历史行为保留影响越久。
# 30 表示约一个月内的行为仍具有明显参考价值。
TIME_DECAY_DAYS = 30

# 搜索历史读取条数，避免历史搜索过多影响当前兴趣判断。
SEARCH_LIMIT = 50


# =========================
# 2. 通用工具函数
# =========================

def _to_float(value, default=0.0):
    """将数据库中的数值安全转换为 float。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_text(value):
    """将文本字段转换为便于匹配的字符串。"""
    if value is None:
        return ""
    return str(value).strip().lower()


def _days_from_now(dt):
    """计算某个时间距离当前时间的天数。"""
    if not dt:
        return 0

    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return 0

    return max((datetime.now() - dt).days, 0)


def time_decay(created_at, decay_days=TIME_DECAY_DAYS):
    """
    时间衰减函数。

    公式：
        decay = e ^ (-d / T)

    其中：
        d 表示行为距离当前时间的天数；
        T 表示时间衰减周期。
    """
    days = _days_from_now(created_at)
    return math.exp(-days / decay_days)


def season_score(season_months):
    """
    季节得分。

    为避免重复计算，季节因素只在最终推荐得分中作为独立因子出现。
    当前月份属于商品应季月份时，返回 1.0，否则返回 0.0。
    """
    now_month = datetime.now().month

    try:
        months = {
            int(x)
            for x in (season_months or "").split(",")
            if str(x).strip()
        }
    except ValueError:
        months = set()

    return 1.0 if now_month in months else 0.0


def normalize(value, max_value):
    """最大值归一化，将不同量纲的得分压缩到 0 到 1 之间。"""
    if max_value <= 0:
        return 0.0
    return value / max_value


# =========================
# 3. 相似度与搜索匹配
# =========================

def cosine_similarity(vec_a, vec_b):
    """
    计算两个商品向量之间的余弦相似度。

    商品向量示例：
        商品A = {用户1: 1.0, 用户2: 3.0, 用户5: 4.0}
        商品B = {用户1: 2.0, 用户3: 1.0, 用户5: 3.0}

    如果两个商品经常被同一批用户浏览、关注或加购，则相似度较高。
    """
    common_users = set(vec_a) & set(vec_b)
    if not common_users:
        return 0.0

    numerator = sum(vec_a[u] * vec_b[u] for u in common_users)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return numerator / (norm_a * norm_b)


def keyword_match_score(keyword, product):
    """
    计算搜索关键词与商品之间的匹配得分。

    匹配规则：
    1. 命中商品名称：1.00
    2. 命中商品类别：0.80
    3. 命中商品介绍：0.60
    4. 命中商品产地：0.50

    这样可以让“搜索”真正影响推荐结果。例如用户搜索“苹果”，
    系统会提高名称中包含苹果的商品，以及相关类别商品的推荐得分。
    """
    kw = _to_text(keyword)
    if not kw:
        return 0.0

    name = _to_text(product.get("name"))
    category = _to_text(product.get("category_name"))
    description = _to_text(product.get("description"))
    origin = _to_text(product.get("origin"))

    score = 0.0

    if kw in name or (name and name in kw):
        score = max(score, 1.00)

    if kw in category or (category and category in kw):
        score = max(score, 0.80)

    if description and kw in description:
        score = max(score, 0.60)

    if origin and kw in origin:
        score = max(score, 0.50)

    # 对包含空格的关键词做简单拆分，增强英文或多词搜索的兼容性。
    # 中文关键词通常不受此逻辑影响。
    for token in kw.split():
        if not token:
            continue
        if token in name:
            score = max(score, 0.70)
        elif token in category:
            score = max(score, 0.55)
        elif token in description:
            score = max(score, 0.40)
        elif token in origin:
            score = max(score, 0.35)

    return score


# =========================
# 4. 数据读取函数
# =========================

def fetch_active_products():
    """读取所有上架商品。"""
    return query_all("""
        SELECT p.*, c.name AS category_name, c.season_months,
               u.username AS seller_name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        JOIN users u ON p.seller_id = u.id
        WHERE p.status='active'
    """)


def fetch_user_actions(user_id):
    """读取目标用户的商品行为记录。"""
    return query_all("""
        SELECT ua.*, p.category_id, c.season_months
        FROM user_actions ua
        LEFT JOIN products p ON ua.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE ua.user_id=%s
        ORDER BY ua.created_at DESC
    """, (user_id,))


def fetch_all_product_actions():
    """读取所有带商品 id 的行为记录，用于构建商品-用户行为向量。"""
    return query_all("""
        SELECT user_id, product_id, action_type, score, created_at
        FROM user_actions
        WHERE product_id IS NOT NULL
    """)


def fetch_search_history(user_id):
    """
    读取用户搜索历史。

    v3 系统中一般使用 search_history.keyword 保存搜索关键词。
    这里保留异常处理，避免个别旧数据库没有该表或字段时导致系统崩溃。
    """
    try:
        return query_all("""
            SELECT keyword, created_at
            FROM search_history
            WHERE user_id=%s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, SEARCH_LIMIT))
    except Exception:
        return []


# =========================
# 5. 得分计算函数
# =========================

def get_action_weight(action):
    """
    计算单条用户行为的有效权重。

    行为有效权重 = 行为基础权重 × 时间衰减系数

    注意：
    季节因素不在这里乘入，避免重复计算。
    """
    action_type = action.get("action_type")
    base_weight = _to_float(
        action.get("score"),
        ACTION_WEIGHT.get(action_type, 1.0)
    )

    return base_weight * time_decay(action.get("created_at"))


def popularity_raw_score(product):
    """
    计算商品原始热度。

    购买行为通常比浏览行为更能代表商品受欢迎程度，因此购买次数权重更高。
    如果数据库中没有 favorite_count、cart_count 字段，会自动按 0 处理。
    """
    view_count = _to_float(product.get("view_count"))
    buy_count = _to_float(product.get("buy_count"))
    favorite_count = _to_float(product.get("favorite_count"))
    cart_count = _to_float(product.get("cart_count"))

    return (
        view_count * 1.0
        + favorite_count * 2.0
        + cart_count * 3.0
        + buy_count * 5.0
    )


def build_user_interest(actions):
    """
    根据目标用户历史行为，构建：
    1. 用户对商品的兴趣强度；
    2. 用户对类别的兴趣强度；
    3. 用户已经互动过的商品集合。
    """
    user_product_interest = defaultdict(float)
    user_category_interest = defaultdict(float)
    interacted_products = set()

    for action in actions:
        product_id = action.get("product_id")
        category_id = action.get("category_id")
        weight = get_action_weight(action)

        if product_id:
            user_product_interest[product_id] += weight
            interacted_products.add(product_id)

        if category_id:
            user_category_interest[category_id] += weight

    return user_product_interest, user_category_interest, interacted_products


def build_search_interest(search_history, products):
    """
    根据搜索历史构建搜索意图得分。

    搜索行为不一定对应某个具体商品 id，因此这里通过关键词与商品名称、
    类别、介绍和产地进行匹配，将搜索关键词转化为商品层面的推荐得分。
    """
    search_product_interest = defaultdict(float)

    for record in search_history:
        keyword = record.get("keyword")
        if not keyword:
            continue

        # 搜索是主动需求，因此使用 search 权重，并叠加时间衰减。
        base_weight = ACTION_WEIGHT["search"] * time_decay(record.get("created_at"))

        for product in products:
            match = keyword_match_score(keyword, product)
            if match > 0:
                search_product_interest[product["id"]] += base_weight * match

    return search_product_interest


def build_item_user_vectors(all_actions):
    """
    构建商品-用户行为向量。

    结构示例：
        {
            商品id1: {用户id1: 权重, 用户id2: 权重},
            商品id2: {用户id3: 权重}
        }
    """
    item_user_vector = defaultdict(lambda: defaultdict(float))

    for action in all_actions:
        product_id = action.get("product_id")
        user_id = action.get("user_id")

        if not product_id or not user_id:
            continue

        weight = get_action_weight(action)
        item_user_vector[product_id][user_id] += weight

    return item_user_vector


def collaborative_filtering_score(candidate_id, user_product_interest, item_user_vector):
    """
    计算候选商品的物品协同过滤得分。

    采用“相似度加权平均”的方式：
        CF(u,i) = Σ sim(i,j) × interest(u,j) / Σ |sim(i,j)|

    其中：
        i 是候选商品；
        j 是用户历史互动过的商品；
        interest(u,j) 是用户对历史商品 j 的兴趣强度。
    """
    numerator = 0.0
    denominator = 0.0

    candidate_vector = item_user_vector.get(candidate_id, {})

    for old_product_id, old_interest in user_product_interest.items():
        old_vector = item_user_vector.get(old_product_id, {})
        sim = cosine_similarity(candidate_vector, old_vector)

        if sim <= 0:
            continue

        numerator += sim * old_interest
        denominator += abs(sim)

    if denominator == 0:
        return 0.0

    return numerator / denominator


# =========================
# 6. 主推荐函数
# =========================

def get_recommendations(user_id=None, limit=8):
    """
    获取推荐商品列表。

    返回值与原系统保持一致：返回商品字典列表。
    因此原来的首页模板、路由和调用方式无需修改。
    """
    products = fetch_active_products()
    if not products:
        return []

    # 商品热度最大值，用于归一化。
    max_popularity = max(popularity_raw_score(p) for p in products) or 1.0

    def cold_start_score(product):
        """
        冷启动推荐得分。

        未登录用户或缺少行为数据的用户，无法进行个性化协同过滤，
        因此主要依据商品热度和季节因素进行推荐。
        """
        popularity_score = normalize(popularity_raw_score(product), max_popularity)
        s_score = season_score(product.get("season_months"))
        return 0.75 * popularity_score + 0.25 * s_score

    # 未登录用户：直接使用冷启动推荐。
    if not user_id:
        return sorted(products, key=cold_start_score, reverse=True)[:limit]

    actions = fetch_user_actions(user_id)
    search_history = fetch_search_history(user_id)

    # 如果用户没有商品行为，也没有搜索历史，则使用冷启动推荐。
    if len(actions) < 2 and not search_history:
        return sorted(products, key=cold_start_score, reverse=True)[:limit]

    # 1. 构建用户行为兴趣画像
    user_product_interest, user_category_interest, interacted_products = build_user_interest(actions)

    # 2. 构建搜索意图得分，让搜索行为进入推荐算法
    search_product_interest = build_search_interest(search_history, products)

    # 3. 构建商品-用户向量，用于物品协同过滤
    all_actions = fetch_all_product_actions()
    item_user_vector = build_item_user_vectors(all_actions)

    # 4. 逐个候选商品计算各部分原始得分
    candidates = []

    for product in products:
        product_id = product["id"]

        # 已经明确互动过的商品不再作为推荐结果展示，避免重复推荐。
        # 如果希望“看过的商品也继续推荐”，可删除下面两行。
        if product_id in interacted_products:
            continue

        cf_raw = collaborative_filtering_score(
            product_id,
            user_product_interest,
            item_user_vector
        )

        search_raw = search_product_interest.get(product_id, 0.0)
        category_raw = user_category_interest.get(product.get("category_id"), 0.0)
        popularity_raw = popularity_raw_score(product)
        season_raw = season_score(product.get("season_months"))

        candidates.append({
            "product": product,
            "cf_raw": cf_raw,
            "search_raw": search_raw,
            "category_raw": category_raw,
            "popularity_raw": popularity_raw,
            "season_raw": season_raw,
        })

    # 如果用户已经互动过所有商品，则退回冷启动推荐。
    if not candidates:
        return sorted(products, key=cold_start_score, reverse=True)[:limit]

    # 5. 计算各项最大值，用于归一化
    max_cf = max(c["cf_raw"] for c in candidates) or 1.0
    max_search = max(c["search_raw"] for c in candidates) or 1.0
    max_category = max(c["category_raw"] for c in candidates) or 1.0
    max_pop = max(c["popularity_raw"] for c in candidates) or 1.0

    # 6. 综合评分
    scored_products = []

    for c in candidates:
        cf_score = normalize(c["cf_raw"], max_cf)
        search_score = normalize(c["search_raw"], max_search)
        category_score = normalize(c["category_raw"], max_category)
        popularity_score = normalize(c["popularity_raw"], max_pop)
        s_score = c["season_raw"]

        final_score = (
            FINAL_WEIGHT["cf"] * cf_score
            + FINAL_WEIGHT["search"] * search_score
            + FINAL_WEIGHT["category"] * category_score
            + FINAL_WEIGHT["popularity"] * popularity_score
            + FINAL_WEIGHT["season"] * s_score
        )

        scored_products.append((final_score, c["product"]))

    scored_products.sort(key=lambda x: x[0], reverse=True)

    return [product for _, product in scored_products[:limit]]
