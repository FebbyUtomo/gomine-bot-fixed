module.exports = {
  apps: [{
    name: 'gomine-bot',
    cwd: '/root/projects/gomine-bot-fixed',
    script: 'gomine.py',
    interpreter: 'python3',
    args: '--max-ads 5 --loop --interval 21600',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file: '/root/.pm2/logs/gomine-bot-error.log',
    out_file: '/root/.pm2/logs/gomine-bot-out.log',
    autorestart: true,
    max_restarts: 10,
    restart_delay: 30000,
    env: {
      PYTHONUNBUFFERED: '1',
    }
  }]
};
