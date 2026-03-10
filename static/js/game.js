// 添加游戏控制变量
let coinGame = null;
let gameContainer = null;
let isGenerating = false;
let abortController = null;

// 创建游戏容器
function createGameContainer() {
    // 先清除任何已存在的容器
    if (gameContainer) {
        gameContainer.remove();
        gameContainer = null;
    }
    
    // 创建新的容器
    gameContainer = document.createElement('div');
    gameContainer.className = 'game-container';
    
    // 重要 - 重置所有可能影响位置的CSS属性
    gameContainer.style.cssText = '';
    
    // 设置基本样式
    gameContainer.style.position = 'fixed';
    gameContainer.style.top = '50%';
    gameContainer.style.left = '50%';
    gameContainer.style.transform = 'translate(-50%, -50%)';
    gameContainer.style.width = '440px';
    gameContainer.style.height = '640px';
    gameContainer.style.backgroundColor = '#222';
    gameContainer.style.padding = '20px';
    gameContainer.style.borderRadius = '10px';
    gameContainer.style.boxShadow = '0 0 15px rgba(0,0,0,0.7)';
    gameContainer.style.border = '1px solid #444';
    gameContainer.style.zIndex = '9999';
    
    // 添加到body之前，先确保没有任何旧的游戏容器
    const existingContainers = document.querySelectorAll('.game-container');
    existingContainers.forEach(container => {
        if (container !== gameContainer) {
            container.remove();
        }
    });
    
    // 添加到body
    document.body.appendChild(gameContainer);
}

// 初始化游戏
function initGame() {
    if (coinGame) {
        // 如果已存在，完全清除并重新创建
        cleanupGame();
    }
    
    createGameContainer();
    coinGame = new CoinGame();
}

// 开始游戏
function startGame() {
    if (!coinGame) {
        initGame();
    }
}

// 停止游戏
function stopGame() {
    if (!coinGame) {
        return;
    }
    if (!coinGame.isExited) {
        coinGame.stop();
        // 在游戏停止后，尝试触发生成完成事件（用于测试）
        setTimeout(() => {
            document.dispatchEvent(new CustomEvent('generating_completed'));
        }, 500);
    }
}

// 监听游戏退出事件
document.addEventListener('gameExit', () => {
    if (isGenerating && abortController) {
        isGenerating = false;
        abortController.abort();
    }
    cleanupGame();
});

// 添加调试事件监听，捕获所有自定义事件
document.addEventListener('generating_completed', (event) => {
    // 如果游戏存在但未开始游戏，直接关闭
    if (coinGame) {
        if (!coinGame.isPlaying && !coinGame.gameOverShown) {
            // 游戏未开始且未显示结束画面，自动关闭
            cleanupGame();
        }
    }
});

// 捕获所有事件监听
const originalAddEventListener = document.addEventListener;
document.addEventListener = function(type, listener, options) {
    return originalAddEventListener.call(this, type, listener, options);
};

const originalDispatchEvent = document.dispatchEvent;
document.dispatchEvent = function(event) {
    return originalDispatchEvent.call(this, event);
};

// 清理游戏
function cleanupGame() {
    if (!coinGame) {
        return;
    }
                
    if (gameContainer) {
        gameContainer.remove();
        gameContainer = null;
    }
    coinGame = null;
}

class CoinGame {
    constructor() {
        this.score = 0;
        this.highScore = localStorage.getItem('coinGameHighScore') || 0;
        this.isPlaying = false;
        this.isExited = false;
        this.gameOverShown = false; // 添加变量跟踪是否显示了游戏结束画面
        this.coins = [];
        this.dropSpeed = 3;
        
        // 创建Canvas并设置样式使其居中
        this.canvas = document.createElement('canvas');
        this.canvas.width = 400;
        this.canvas.height = 600;
        
        // 强制覆盖Canvas样式，确保它在容器中居中
        this.canvas.style.cssText = 'display: block !important; margin: 0 auto !important; position: static !important; left: auto !important; top: auto !important; transform: none !important;';
        
        this.ctx = this.canvas.getContext('2d');
        
        // 设置金币大小（vh单位）
        this.coinSizes = {
            1: 7,  // 1分金币 7vh
            2: 6,  // 2分金币 6vh
            3: 5,  // 3分金币 5vh
            4: 4,  // 4分金币 4vh
            5: 3   // 5分金币 3vh
        };
        
        this.spawnRate = 500; // 每500毫秒生成一个新金币
        this.lastSpawn = 0;
        
        // 定义标题栏高度和内边距
        this.headerHeight = 80;
        this.padding = 20;
        
        // 定义游戏区域的起始位置
        this.gameAreaStartY = this.headerHeight;
        
        // 将画布添加到游戏容器中
        const gameContainer = document.querySelector('.game-container');
        if (gameContainer) {
            // 清除游戏容器内部的所有样式并设置
            gameContainer.innerHTML = '';
            gameContainer.style.cssText += 'text-align: center !important; display: flex !important; justify-content: center !important; align-items: center !important; flex-direction: column !important;';
            
            // 添加Canvas
            gameContainer.appendChild(this.canvas);
            
            // 创建并添加加载图像容器在游戏内部居中
            this.createLoadingImage(gameContainer);
        }
        
        this.setupEventListeners();
        
        // 初始绘制界面
        this.drawLoadingScreen();
    }
    
    // 创建加载图像
    createLoadingImage(container) {
        // 移除任何现有的加载图像
        const existingLoader = document.getElementById('game-loading-container');
        if (existingLoader) {
            existingLoader.remove();
        }
        
        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'game-loading-container';
        
        // 设置加载容器样式 - 使其宽度占满父容器
        loadingDiv.style.cssText = 'position: absolute !important; top: 50% !important; left: 50% !important; transform: translate(-50%, -50%) !important; width: 80% !important; height: auto !important; z-index: 10000 !important; background-color: transparent !important;';
        
        // 创建图像元素
        const img = document.createElement('img');
        img.src = '/static/media/loading.gif';
        img.alt = '加载中';
        
        // 设置图像样式 - 确保宽度100%占满父容器
        img.style.cssText = 'width: 20% !important; height: auto !important; object-fit: contain !important; max-width: 20% !important;';
        
        loadingDiv.appendChild(img);
        container.appendChild(loadingDiv);
        
        this.loadingContainer = loadingDiv;
    }

    // 将vh单位转换为像素
    vhToPx(vh) {
        return (vh * window.innerHeight) / 100;
    }
    
    // 绘制加载画面
    drawLoadingScreen() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制背景
        this.ctx.fillStyle = '#1a1a1a';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制标题栏背景
        this.ctx.fillStyle = '#222';
        this.ctx.fillRect(0, 0, this.canvas.width, this.headerHeight);
        
        // 绘制分隔线
        this.ctx.strokeStyle = '#444';
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(0, this.headerHeight);
        this.ctx.lineTo(this.canvas.width, this.headerHeight);
        this.ctx.stroke();
        
        // 绘制标题
        this.ctx.fillStyle = '#ccc';
        this.ctx.font = '16px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('生成过程耗时较久，玩个游戏放松一下', this.canvas.width/2, 30);
        
        // 绘制分数
        this.ctx.font = '14px Arial';
        this.ctx.textAlign = 'left';
        this.ctx.fillText(`分数: ${this.score}`, this.padding, 60);
        this.ctx.textAlign = 'right';
        this.ctx.fillText(`最高分: ${this.highScore}`, this.canvas.width - this.padding, 60);
        
        // 绘制开始游戏按钮
        const buttonWidth = 80;
        const buttonHeight = 25;
        const buttonX = (this.canvas.width - buttonWidth) / 2;
        const buttonY = 45;
        
        this.ctx.fillStyle = '#2e7d32'; // 绿色按钮
        this.ctx.fillRect(buttonX, buttonY, buttonWidth, buttonHeight);
        this.ctx.fillStyle = '#eee';
        this.ctx.font = '14px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('开始游戏', buttonX + buttonWidth/2, buttonY + 17);
    }

    setupEventListeners() {
        this.canvas.addEventListener('mousedown', (e) => {
            // 获取画布在页面中的位置
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;
            
            // 计算点击位置相对于画布的实际坐标
            const actualX = (e.clientX - rect.left) * scaleX;
            const actualY = (e.clientY - rect.top) * scaleY;
            
            // 检查是否点击了按钮
            const buttonWidth = this.isPlaying ? 60 : 80;
            const buttonHeight = 25;
            const buttonX = (this.canvas.width - buttonWidth) / 2;
            const buttonY = 45;
            
            // 只检查按钮本身的区域
            if (actualX >= buttonX && actualX <= buttonX + buttonWidth &&
                actualY >= buttonY && actualY <= buttonY + buttonHeight) {
                if (this.isPlaying) {
                    this.exitGame();
                } else {
                    this.start();
                }
                return;
            }
            
            // 如果游戏正在运行，处理金币点击
            if (this.isPlaying) {
                this.coins = this.coins.filter(coin => {
                    if (this.isClickedOnCoin(e.clientX, e.clientY, coin)) {
                        this.score += coin.points;
                        return false;
                    }
                    return true;
                });
            }
        });

        // 添加鼠标移动事件监听器
        this.canvas.addEventListener('mousemove', (e) => {
            // 检查是否在按钮上
            const buttonWidth = this.isPlaying ? 60 : 80;
            const buttonHeight = 25;
            const buttonX = (this.canvas.width - buttonWidth) / 2;
            const buttonY = 45;
            
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;
            
            const actualX = (e.clientX - rect.left) * scaleX;
            const actualY = (e.clientY - rect.top) * scaleY;
            
            // 检查是否在按钮上或金币上
            const isOverButton = actualX >= buttonX && actualX <= buttonX + buttonWidth &&
                               actualY >= buttonY && actualY <= buttonY + buttonHeight;
            const isOverCoin = this.isPlaying && this.coins.some(coin => this.isClickedOnCoin(e.clientX, e.clientY, coin));
            
            this.canvas.style.cursor = (isOverButton || isOverCoin) ? 'pointer' : 'default';
        });
    }

    // 开始游戏
    start() {
        this.isPlaying = true;
        this.isExited = false;
        this.score = 0;
        this.coins = [];
        this.lastSpawn = Date.now();
        
        // 隐藏加载动画
        if (this.loadingContainer) {
            this.loadingContainer.style.display = 'none';
        }
        
        this.gameLoop();
    }

    stop() {
        this.isPlaying = false;
        if (this.score > parseInt(this.highScore)) {
            this.highScore = this.score;
            localStorage.setItem('coinGameHighScore', this.score);
        }
        this.gameOverShown = true; // 标记已显示游戏结束画面
        this.showGameOver();
        
        // 根据游戏状态处理生成完成
        if (!isGenerating) {
            // 生成已经结束，但游戏还在显示，触发事件关闭游戏
            setTimeout(() => {
                document.dispatchEvent(new CustomEvent('generating_completed'));
            }, 100);
        }
    }

    exitGame() {
        this.isExited = true;
        this.stop();
        
        // 触发自定义事件通知父窗口
        const event = new CustomEvent('gameExit');
        document.dispatchEvent(event);
    }

    createCoin() {
        const points = Math.floor(Math.random() * 5) + 1; // 1-5分
        const coinSize = this.vhToPx(this.coinSizes[points]); // 根据分值设置大小
        
        return {
            x: Math.random() * (this.canvas.width - coinSize),
            y: this.headerHeight, // 从标题栏底部开始掉落
            size: coinSize,
            points: points,
            color: points === 5 ? '#FFD700' : // 5分金币 - 金色
                   points === 4 ? '#C0C0C0' : // 4分金币 - 银色
                   points === 3 ? '#CD7F32' : // 3分金币 - 铜色
                   points === 2 ? '#9370DB' : // 2分金币 - 紫色
                   '#4682B4'                  // 1分金币 - 蓝色
        };
    }

    isClickedOnCoin(x, y, coin) {
        // 计算点击位置相对于画布的实际坐标
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        const actualX = (x - rect.left) * scaleX;
        const actualY = (y - rect.top) * scaleY;
        
        // 计算金币中心点
        const centerX = coin.x + coin.size/2;
        const centerY = coin.y + coin.size/2;
        
        // 计算点击位置到金币中心的距离
        const distance = Math.sqrt(
            Math.pow(actualX - centerX, 2) +
            Math.pow(actualY - centerY, 2)
        );
        
        // 如果距离小于金币半径，则表示点击在金币上
        return distance <= coin.size/2;
    }

    update() {
        const now = Date.now();
        
        // 生成新金币
        if (now - this.lastSpawn >= this.spawnRate) {
            this.coins.push(this.createCoin());
            this.lastSpawn = now;
        }
        
        // 更新金币位置
        this.coins = this.coins.filter(coin => {
            coin.y += this.dropSpeed;
            // 只有当金币完全离开画布时才移除
            return coin.y < this.canvas.height + coin.size;
        });
    }

    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制背景
        this.ctx.fillStyle = '#1a1a1a';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制标题栏背景
        this.ctx.fillStyle = '#222';
        this.ctx.fillRect(0, 0, this.canvas.width, this.headerHeight);
        
        // 绘制分隔线
        this.ctx.strokeStyle = '#444';
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.moveTo(0, this.headerHeight);
        this.ctx.lineTo(this.canvas.width, this.headerHeight);
        this.ctx.stroke();
        
        // 绘制标题
        this.ctx.fillStyle = '#ccc';
        this.ctx.font = '16px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('生成过程耗时较久，玩个游戏放松一下', this.canvas.width/2, 30);
        
        // 绘制分数
        this.ctx.font = '14px Arial';
        this.ctx.textAlign = 'left';
        this.ctx.fillText(`分数: ${this.score}`, this.padding, 60);
        this.ctx.textAlign = 'right';
        this.ctx.fillText(`最高分: ${this.highScore}`, this.canvas.width - this.padding, 60);
        
        // 绘制停止按钮
        const buttonWidth = 60;
        const buttonHeight = 25;
        const buttonX = (this.canvas.width - buttonWidth) / 2;
        const buttonY = 45;
        
        this.ctx.fillStyle = '#d32f2f'; // 深红色按钮
        this.ctx.fillRect(buttonX, buttonY, buttonWidth, buttonHeight);
        this.ctx.fillStyle = '#eee';
        this.ctx.font = '14px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('停止游戏', buttonX + buttonWidth/2, buttonY + 17);
        
        // 添加金币光晕效果
        this.coins.forEach(coin => {
            // 绘制光晕
            const gradient = this.ctx.createRadialGradient(
                coin.x + coin.size/2,
                coin.y + coin.size/2,
                0,
                coin.x + coin.size/2,
                coin.y + coin.size/2,
                coin.size
            );
            gradient.addColorStop(0, coin.color);
            gradient.addColorStop(1, 'rgba(0,0,0,0)');
            
            this.ctx.beginPath();
            this.ctx.arc(
                coin.x + coin.size/2,
                coin.y + coin.size/2,
                coin.size * 0.8,
                0,
                Math.PI * 2
            );
            this.ctx.fillStyle = gradient;
            this.ctx.fill();
            this.ctx.closePath();
            
            // 绘制金币
            this.ctx.beginPath();
            this.ctx.arc(
                coin.x + coin.size/2,
                coin.y + coin.size/2,
                coin.size/2,
                0,
                Math.PI * 2
            );
            this.ctx.fillStyle = coin.color;
            this.ctx.fill();
            this.ctx.closePath();

            // 绘制分值
            this.ctx.fillStyle = '#fff';
            this.ctx.font = `${coin.size/2}px Arial`;
            this.ctx.textAlign = 'center';
            this.ctx.fillText(
                coin.points,
                coin.x + coin.size/2,
                coin.y + coin.size/2 + coin.size/6
            );
        });
    }

    showGameOver() {
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 创建渐变背景
        const gradient = this.ctx.createLinearGradient(0, 0, 0, this.canvas.height);
        gradient.addColorStop(0, 'rgba(40, 40, 40, 0.8)');
        gradient.addColorStop(1, 'rgba(10, 10, 10, 0.8)');
        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 添加边框
        this.ctx.strokeStyle = '#666';
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(50, this.canvas.height/2 - 100, this.canvas.width - 100, 200);
        
        this.ctx.fillStyle = '#ddd';
        this.ctx.font = '24px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('游戏结束', this.canvas.width/2, this.canvas.height/2 - 30);
        this.ctx.fillText(`最终得分: ${this.score}`, this.canvas.width/2, this.canvas.height/2 + 10);
        this.ctx.font = '16px Arial';
        this.ctx.fillText('点击窗口外任意位置关闭', this.canvas.width/2, this.canvas.height/2 + 50);

        // 添加点击事件监听器到document
        const clickHandler = (e) => {
            // 检查点击是否在canvas外
            const rect = this.canvas.getBoundingClientRect();
            
            if (e.clientX < rect.left || e.clientX > rect.right ||
                e.clientY < rect.top || e.clientY > rect.bottom) {
                document.removeEventListener('click', clickHandler);
                if (!this.isExited) {
                    this.exitGame();
                }
            }
        };
        document.addEventListener('click', clickHandler);
    }

    gameLoop() {
        if (!this.isPlaying) return;
        
        this.update();
        this.draw();
        requestAnimationFrame(() => this.gameLoop());
    }
}
