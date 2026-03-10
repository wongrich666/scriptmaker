document.addEventListener('DOMContentLoaded', function() {
    // 检查导航栏是否存在
    const navbar = document.querySelector('.navbar-nav');
    
    if (navbar) {
        // 创建一个新的导航项
        const themeToggleItem = document.createElement('li');
        themeToggleItem.className = 'nav-item';
        
        // 创建主题切换按钮
        const themeToggle = document.createElement('button');
        themeToggle.className = 'nav-link btn';
        themeToggle.style.background = 'none';
        themeToggle.style.border = 'none';
        themeToggle.style.cursor = 'pointer';
        themeToggle.innerHTML = '🌓';
        themeToggle.setAttribute('aria-label', '切换主题');
        themeToggle.setAttribute('title', '切换主题');
        
        // 将按钮添加到导航项
        themeToggleItem.appendChild(themeToggle);
        
        // 将导航项插入到导航栏中
        navbar.insertBefore(themeToggleItem, navbar.lastElementChild);
        
        // 检测系统颜色方案偏好
        const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)');
        
        // 检查本地存储中的主题首选项
        const storedTheme = localStorage.getItem('theme');
        
        // 登录和注册页面使用系统默认主题
        const isLoginPage = window.location.pathname.includes('login') || window.location.pathname.includes('register') || window.location.pathname === '/';
        
        if (storedTheme === 'dark' || (isLoginPage && prefersDarkScheme.matches && !storedTheme)) {
            document.body.classList.add('dark-theme');
        }
        
        // 切换主题的事件监听器
        themeToggle.addEventListener('click', function() {
            document.body.classList.toggle('dark-theme');
            
            // 将当前主题保存到本地存储
            if (document.body.classList.contains('dark-theme')) {
                localStorage.setItem('theme', 'dark');
            } else {
                localStorage.setItem('theme', 'light');
            }
        });
    } else {
        console.warn('导航栏不存在，无法添加主题切换按钮');
    }
}); 