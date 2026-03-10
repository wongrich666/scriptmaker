# SQL控制台工具

这是一个简单的命令行工具，用于执行SQL语句并查看/更新SQLite数据库中的数据。

## 使用方法

### 基本使用

```
python db_console.py
```

默认情况下，程序将连接到当前目录下的`users.db`文件。

### 指定数据库文件

```
python db_console.py 路径/到/你的数据库.db
```

## 功能特点

- 执行任何SQL查询（SELECT, INSERT, UPDATE, DELETE等）
- 自动格式化和显示查询结果
- 显示受影响的行数
- 简单的错误处理

## 命令示例

查询所有用户：
```
SQL> SELECT * FROM users
```

插入新用户：
```
SQL> INSERT INTO users (name, email, age) VALUES ('张三', 'zhangsan@example.com', 30)
```

更新用户信息：
```
SQL> UPDATE users SET age = 31 WHERE name = '张三'
```

删除用户：
```
SQL> DELETE FROM users WHERE name = '张三'
```

退出程序：
```
SQL> exit
```
或
```
SQL> quit
```