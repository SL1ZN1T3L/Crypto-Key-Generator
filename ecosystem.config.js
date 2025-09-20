module.exports = {
  apps: [{
    name: 'crypto-bot',
    script: './bot.py',
    interpreter: 'python3',
    instances: 1,
    exec_mode: 'fork',
    // Логи PM2
    error_file: './logs/pm2-error.log',
    out_file: './logs/pm2-out.log',
    log_file: './logs/pm2.log',
    time: true,
    // Авторестарт
    max_memory_restart: '500M',
    // Кастомные переменные
    env: {
      NODE_ENV: 'production'
    }
  }]
};