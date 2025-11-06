/**
 * API 配置文件
 * 
 * 使用方式：
 * 1. 開發環境：使用 localhost
 * 2. 生產環境：修改 BACKEND_URL 為實際的後端網域
 */

// =====================================
// 後端 API 網域設定
// =====================================

// 開發環境（本地）
const BACKEND_URL_DEV = "http://localhost:8000";

// 生產環境（請修改為實際的後端網域）
const BACKEND_URL_PROD = "https://bda-final-project.onrender.com";

// =====================================
// 自動環境檢測
// =====================================

// 判斷當前是否為生產環境
const isProduction = window.location.hostname !== 'localhost' 
                  && window.location.hostname !== '127.0.0.1'
                  && !window.location.hostname.startsWith('192.168.');

// 根據環境自動選擇 API 網域
const API_BASE = isProduction ? BACKEND_URL_PROD : BACKEND_URL_DEV;

// =====================================
// API 端點配置
// =====================================

const API_CONFIG = {
    // 基礎網域
    BASE_URL: API_BASE,
    
    // API 端點
    ENDPOINTS: {
        PROCESS_AUDIO: `${API_BASE}/process_audio/`,
        PROCESS_YOUTUBE: `${API_BASE}/process_youtube/`,
        HEALTH: `${API_BASE}/health`,
        ROOT: `${API_BASE}/`
    },
    
    // 請求超時設定（毫秒）
    TIMEOUT: 300000, // 5 分鐘
    
    // 其他設定
    MAX_FILE_SIZE: 500 * 1024 * 1024, // 500MB
};

// =====================================
// 輔助函數
// =====================================

/**
 * 檢查 API 是否可用
 */
async function checkAPIHealth() {
    try {
        const response = await fetch(API_CONFIG.ENDPOINTS.HEALTH, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('✅ API 連接正常:', data);
            return true;
        } else {
            console.error('❌ API 連接失敗:', response.status);
            return false;
        }
    } catch (error) {
        console.error('❌ 無法連接到 API:', error.message);
        return false;
    }
}

/**
 * 獲取完整的 API URL
 */
function getAPIUrl(endpoint) {
    return API_CONFIG.ENDPOINTS[endpoint] || API_CONFIG.BASE_URL;
}

// =====================================
// 環境資訊顯示（開發用）
// =====================================

console.log('🌍 環境資訊:');
console.log('  - 當前環境:', isProduction ? '生產環境' : '開發環境');
console.log('  - API 網域:', API_BASE);
console.log('  - 前端域名:', window.location.hostname);

// =====================================
// 導出配置（供其他文件使用）
// =====================================

// 如果使用模組化開發，可以使用以下導出方式：
// export { API_CONFIG, checkAPIHealth, getAPIUrl };

// 如果直接在 HTML 中引用，配置會自動掛載到全域變數