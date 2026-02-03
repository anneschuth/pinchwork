"""CSS styles for the admin dashboard.

Separated for maintainability. See admin_dashboard.py for usage.
"""

ADMIN_CSS = """\
  body {
    font-family: Verdana, Geneva, sans-serif;
    font-size: 10pt;
    background: #1a1a2e;
    color: #e0e0e0;
    margin: 0;
    padding: 0;
  }
  .container {
    max-width: 960px;
    margin: 0 auto;
    background: #16213e;
  }
  .header {
    background: #0f3460;
    color: #e94560;
    padding: 8px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header .title {
    font-weight: bold;
    font-size: 12pt;
    letter-spacing: 1px;
    color: #e94560;
  }
  .header a {
    color: #a0c4ff;
    text-decoration: none;
    font-size: 9pt;
    margin-left: 10px;
  }
  .header a:hover { text-decoration: underline; }
  .section {
    padding: 14px 18px;
    border-bottom: 1px solid #1a1a3e;
  }
  .section h2 {
    font-size: 10pt;
    color: #e94560;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 0 0 10px 0;
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 16px;
  }
  .stat-card {
    background: #1a1a3e;
    border-radius: 6px;
    padding: 12px;
    text-align: center;
  }
  .stat-card .number {
    font-size: 20pt;
    font-weight: bold;
    color: #e94560;
  }
  .stat-card .label {
    font-size: 8pt;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 9pt;
  }
  th {
    text-align: left;
    border-bottom: 1px solid #333;
    padding: 6px 8px;
    font-size: 8pt;
    text-transform: uppercase;
    color: #888;
  }
  td {
    padding: 6px 8px;
    border-bottom: 1px solid #222;
    vertical-align: top;
  }
  tr:hover { background: #1a1a3e; }
  .mono { font-family: monospace; font-size: 8pt; }
  .right { text-align: right; }
  .muted { color: #666; font-size: 8pt; }
  a { color: #a0c4ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .tag {
    display: inline-block;
    background: #2a2a4e;
    color: #a0c4ff;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 8pt;
    margin-right: 4px;
  }
  .badge-infra {
    background: #1a3a5e;
    color: #4da6ff;
  }
  .badge-suspended {
    background: #5e1a1a;
    color: #ff4d4d;
  }
  .chart-container {
    background: #1a1a3e;
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 14px;
  }
  .chart-title {
    font-size: 9pt;
    color: #999;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .detail-row {
    margin-bottom: 10px;
  }
  .detail-label {
    font-size: 8pt;
    text-transform: uppercase;
    color: #888;
    letter-spacing: 0.5px;
  }
  .detail-value {
    margin-top: 2px;
    line-height: 1.5;
  }
  .need-full {
    white-space: pre-wrap;
    word-break: break-word;
    background: #1a1a3e;
    padding: 10px;
    border-radius: 4px;
    font-size: 9pt;
    line-height: 1.6;
  }
  .pagination {
    display: flex;
    gap: 8px;
    margin-top: 14px;
    font-size: 9pt;
  }
  .pagination a, .pagination span {
    padding: 4px 10px;
    border-radius: 3px;
  }
  .pagination .current {
    background: #e94560;
    color: #fff;
  }
  .login-box {
    max-width: 360px;
    margin: 80px auto;
    background: #16213e;
    padding: 30px;
    border-radius: 8px;
  }
  .login-box h2 {
    color: #e94560;
    margin: 0 0 16px 0;
  }
  .login-box input {
    width: 100%;
    padding: 8px;
    margin-bottom: 12px;
    background: #1a1a3e;
    border: 1px solid #333;
    color: #e0e0e0;
    border-radius: 4px;
    font-size: 10pt;
    box-sizing: border-box;
  }
  .login-box button {
    width: 100%;
    padding: 10px;
    background: #e94560;
    color: #fff;
    border: none;
    border-radius: 4px;
    font-size: 10pt;
    cursor: pointer;
  }
  .login-box button:hover { background: #c43050; }
  .login-error {
    color: #ff4d4d;
    font-size: 9pt;
    margin-bottom: 10px;
  }
  .status-posted { color: #4da6ff; }
  .status-claimed { color: #ff9f43; }
  .status-delivered { color: #a855f7; }
  .status-approved { color: #22c55e; }
  .status-expired, .status-cancelled { color: #666; }
  @media (max-width: 600px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    td:nth-child(n+5) { display: none; }
    th:nth-child(n+5) { display: none; }
  }
"""
