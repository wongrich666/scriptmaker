/**
 * 微信二维码调试工具
 * 用于在无法实际扫码的情况下模拟扫码过程
 */

// 模拟扫码
function simulateScan(sceneStr, openid) {
    // 显示模拟信息
    console.log('模拟扫码，场景值:', sceneStr, '微信OpenID:', openid);
    
    // 更新数据库中的二维码状态
    $.ajax({
        url: '/auth/debug_simulate_scan',
        method: 'POST',
        data: {
            scene_str: sceneStr,
            openid: openid || 'test_wx_' + Math.random().toString(36).substr(2, 10)
        },
        success: function(response) {
            console.log('模拟扫码响应:', response);
        },
        error: function(xhr, status, error) {
            console.error('模拟扫码失败:', error);
        }
    });
}

// 添加调试面板
$(document).ready(function() {
    // 只在开发环境中显示调试面板
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
        // 创建调试面板
        const debugPanel = $('<div>').addClass('debug-panel').css({
            position: 'fixed',
            bottom: '10px',
            right: '10px',
            background: 'rgba(0,0,0,0.8)',
            color: '#fff',
            padding: '10px',
            borderRadius: '5px',
            zIndex: 9999,
            fontSize: '12px'
        });
        
        // 添加标题
        debugPanel.append($('<h5>').text('微信扫码调试').css({
            margin: '0 0 10px 0',
            borderBottom: '1px solid #555',
            paddingBottom: '5px'
        }));
        
        // 添加场景值显示
        debugPanel.append($('<div>').attr('id', 'debug-scene-str').text('场景值: 未获取'));
        
        // 添加模拟扫码按钮
        const scanBtn = $('<button>').addClass('btn btn-sm btn-primary mt-2').text('模拟扫码')
            .css({marginRight: '5px'});
        scanBtn.on('click', function() {
            const sceneStr = $('#debug-scene-str').data('scene-str');
            if (sceneStr) {
                simulateScan(sceneStr);
            } else {
                alert('请先获取二维码');
            }
        });
        
        // 添加操作区域
        const actionArea = $('<div>').addClass('mt-2');
        actionArea.append(scanBtn);
        
        // 添加日志区域
        const logArea = $('<div>').addClass('mt-2').css({
            maxHeight: '150px',
            overflowY: 'auto',
            background: '#222',
            padding: '5px',
            borderRadius: '3px',
            fontSize: '11px'
        });
        
        // 添加关闭按钮
        const closeBtn = $('<button>').addClass('btn btn-sm btn-danger').text('X')
            .css({
                position: 'absolute',
                top: '5px',
                right: '5px',
                padding: '0 5px',
                fontSize: '10px'
            });
        closeBtn.on('click', function() {
            debugPanel.hide();
        });
        
        // 组合面板
        debugPanel.append(actionArea).append(logArea).append(closeBtn);
        
        // 添加到页面
        $('body').append(debugPanel);
        
        // 重写console.log以显示在调试面板
        const oldLog = console.log;
        console.log = function() {
            oldLog.apply(console, arguments);
            const args = Array.from(arguments);
            let logItem = $('<div>').css({
                borderBottom: '1px dashed #444',
                paddingBottom: '3px',
                marginBottom: '3px'
            });
            logItem.text(`[${new Date().toLocaleTimeString()}] ` + args.map(arg => 
                typeof arg === 'object' ? JSON.stringify(arg) : arg).join(' '));
            logArea.prepend(logItem);
        };
        
        // 监听获取二维码的请求
        $(document).ajaxSuccess(function(event, xhr, settings) {
            if (settings.url.includes('/wechat_qrcode/')) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    if (response.success && response.scene_str) {
                        $('#debug-scene-str').text('场景值: ' + response.scene_str)
                            .data('scene-str', response.scene_str);
                    }
                } catch (e) {
                    console.error('解析二维码响应失败', e);
                }
            }
        });
    }
}); 