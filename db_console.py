import sqlite3
import sys

def execute_query(db_path, query):
    """执行SQL查询并返回结果"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        
        # 如果是SELECT语句，获取并显示结果
        if query.strip().upper().startswith('SELECT'):
            rows = cursor.fetchall()
            # 获取列名
            column_names = [description[0] for description in cursor.description]
            
            # 打印列名
            print(' | '.join(column_names))
            print('-' * (sum(len(name) for name in column_names) + len(column_names) * 3))
            
            # 打印数据
            for row in rows:
                print(' | '.join(str(item) for item in row))
            
            print(f"\n共 {len(rows)} 条记录")
        else:
            # 如果是其他类型的查询（INSERT, UPDATE, DELETE等），提交更改
            conn.commit()
            print(f"查询执行成功，影响了 {cursor.rowcount} 行数据")
        
        conn.close()
        return True
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return False
    except Exception as e:
        print(f"执行错误: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        db_path = 'users.db'  # 默认数据库路径
    else:
        db_path = sys.argv[1]
    
    print(f"SQL控制台 - 连接到: {db_path}")
    print("输入SQL查询 (输入'exit'或'quit'退出):")
    
    while True:
        # 获取用户输入的SQL语句
        query = input("SQL> ")
        
        # 检查是否退出
        if query.lower() in ('exit', 'quit'):
            break
        
        # 如果输入为空，继续下一轮
        if not query.strip():
            continue
        
        # 执行查询
        execute_query(db_path, query)

if __name__ == "__main__":
    main() 