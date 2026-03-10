import sqlalchemy as sa
from sqlalchemy import create_engine, text, inspect
import sqlite3

# 创建数据库连接
SQLALCHEMY_DATABASE_URL = "sqlite:///users.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)

def table_exists(table_name):
    """检查表是否存在"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def list_all_tables():
    """列出所有表"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"数据库中的所有表: {tables}")
    return tables

def add_column_if_not_exists(conn, table, column, type_with_default):
    """添加列，如果列已存在则忽略错误"""
    try:
        conn.execute(text(f"""
            ALTER TABLE {table} 
            ADD COLUMN {column} {type_with_default}
        """))
        print(f"已添加 {table}.{column} 列")
    except Exception as e:
        if 'duplicate column name' in str(e):
            print(f"列 {table}.{column} 已存在，跳过")
        else:
            print(f"添加 {table}.{column} 时出错: {e}")

def upgrade():
    # 列出所有已有的表
    all_tables = list_all_tables()
    
    # 添加新字段
    with engine.begin() as conn:
        # 添加微信相关字段
        add_column_if_not_exists(conn, 'users', 'wx_openid', 'TEXT DEFAULT NULL')
        add_column_if_not_exists(conn, 'users', 'wx_nickname', 'TEXT DEFAULT NULL')
        add_column_if_not_exists(conn, 'users', 'wx_avatar', 'TEXT DEFAULT NULL')
        add_column_if_not_exists(conn, 'users', 'register_type', "TEXT DEFAULT 'email'")
        
        # 检查是否需要创建二维码状态表
        if not table_exists('wechat_qrcode'):
            print("创建wechat_qrcode表...")
            try:
                conn.execute(text("""
                    CREATE TABLE wechat_qrcode (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scene_str TEXT NOT NULL,
                        scanned BOOLEAN DEFAULT 0,
                        openid TEXT DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        UNIQUE(scene_str)
                    )
                """))
                print("wechat_qrcode表创建成功")
            except Exception as e:
                print(f"创建wechat_qrcode表出错: {e}")
        else:
            print("wechat_qrcode表已存在，跳过创建")
        
        print("数据库迁移完成")
    
    # 显示迁移后的所有表
    list_all_tables()

if __name__ == '__main__':
    upgrade()