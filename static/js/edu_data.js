/* edu_data.js — Tooltip content & mini-lesson data for Newbie Mode */

const EDU_TIPS = {
  rsi: {
    name: "RSI — Chỉ số Sức mạnh",
    what: "Đo xem giá đang bị mua quá hay bán quá, thang điểm 0–100.",
    says_fn: (val) => {
      if (val < 35) return `RSI ${val.toFixed(0)} — Thị trường đang hoảng loạn bán tháo. Có thể sắp phục hồi.`;
      if (val > 65) return `RSI ${val.toFixed(0)} — Nhiều người đang mua vào, giá có thể đang "nóng".`;
      return `RSI ${val.toFixed(0)} — Vùng trung lập, chưa có tín hiệu cực đoan.`;
    },
    action: "Dùng RSI để XÁC NHẬN tín hiệu khác, đừng vào lệnh chỉ vì RSI thấp.",
  },
  macd: {
    name: "MACD — Đà tăng/giảm",
    what: "So sánh 2 đường trung bình để phát hiện đà mua/bán đang thay đổi.",
    says_fn: (val, rising) => {
      if (val > 0 && rising)  return "Đà mua đang mạnh lên — phe mua đang kiểm soát thị trường.";
      if (val > 0 && !rising) return "Đà mua đang yếu dần — cẩn thận với tín hiệu đảo chiều.";
      if (val < 0 && !rising) return "Đà bán đang mạnh — tránh mua mới lúc này.";
      return "Đà bán đang yếu đi — có thể sắp đảo chiều lên.";
    },
    action: "MACD cắt từ âm sang dương = tín hiệu đảo chiều tốt. Chờ thêm xác nhận trước khi vào.",
  },
  adx: {
    name: "ADX — Độ mạnh xu hướng",
    what: "Đo độ mạnh của xu hướng. ADX cao = xu hướng rõ ràng hơn.",
    says_fn: (val) => {
      if (val > 40) return `ADX ${val.toFixed(0)} — Xu hướng rất mạnh, tín hiệu đáng tin cậy hơn.`;
      if (val > 25) return `ADX ${val.toFixed(0)} — Thị trường đang có xu hướng, chiến lược theo trend hiệu quả.`;
      return `ADX ${val.toFixed(0)} — Thị trường đi ngang lộn xộn, nhiều tín hiệu giả.`;
    },
    action: "ADX < 20: KHÔNG giao dịch theo xu hướng. Chờ ADX > 25 mới tin vào breakout.",
  },
  bollinger: {
    name: "Bollinger Bands — Dải giá",
    what: "3 đường bao quanh giá: vùng 'bình thường' của giá. Hiếm khi giá vượt ra ngoài dải.",
    says_fn: (pct) => {
      if (pct === null || pct === undefined) return "Không có dữ liệu Bollinger Bands.";
      const p = (pct * 100).toFixed(0);
      if (pct < 0.2) return `BB Position ${p}% — Giá ở gần dải dưới, vùng tiềm năng mua (cần xác nhận thêm).`;
      if (pct > 0.8) return `BB Position ${p}% — Giá ở gần dải trên, vùng tiềm năng chốt lời.`;
      return `BB Position ${p}% — Giá đang ở giữa dải, chưa có tín hiệu cực đoan.`;
    },
    action: "Giá chạm dải dưới + nhiều tín hiệu khác = mua mạnh hơn. Không mua chỉ vì 'chạm dải dưới'.",
  },
  ema: {
    name: "EMA — Đường xu hướng",
    what: "Đường mượt theo dõi giá, cho biết xu hướng ngắn/trung/dài hạn.",
    says_fn: (price, ema200) => {
      if (!ema200) return "Không có dữ liệu EMA200.";
      if (price > ema200) return `Giá (${price?.toLocaleString()}) trên EMA200 — Xu hướng DÀI HẠN đang tăng. Tốt để mua.`;
      return `Giá (${price?.toLocaleString()}) dưới EMA200 — Xu hướng dài hạn giảm. Giao dịch mua rủi ro cao hơn.`;
    },
    action: "Giá trên EMA200 = an toàn hơn để mua. EMA34 cắt lên EMA89 = tín hiệu đảo chiều tăng.",
  },
  sr: {
    name: "Vùng Hỗ trợ & Kháng cự",
    what: "Mức giá lịch sử nơi thị trường đã nhiều lần bật lên (xanh) hoặc bật xuống (đỏ).",
    says_fn: () => "Các đường trên biểu đồ: xanh = vùng hỗ trợ (giá dễ bật lên), đỏ = kháng cự (giá dễ bị chặn).",
    action: "Mua gần hỗ trợ, chốt lời gần kháng cự. Giá phá kháng cự = cơ hội breakout.",
  },
  buy_score: {
    name: "Buy Score — Điểm Mua",
    what: "Tổng điểm từ 13 tiêu chí kỹ thuật. Càng cao = càng nhiều tín hiệu xác nhận.",
    says_fn: (score) => {
      if (score >= 9)  return `Score ${score}/13 — Rất mạnh! Nhiều chỉ số đồng thuận hướng mua.`;
      if (score >= 7)  return `Score ${score}/13 — Tốt, đủ điều kiện cân nhắc vào lệnh.`;
      if (score >= 4)  return `Score ${score}/13 — Trung bình, nên chờ thêm xác nhận.`;
      return `Score ${score}/13 — Yếu, chưa đủ điều kiện vào lệnh.`;
    },
    action: "Chỉ vào lệnh khi Score vượt ngưỡng tối thiểu trong Strategy Config.",
  },
};

const EDU_LESSONS = [
  {
    id: "rsi_101",
    title: "RSI là gì? (30 giây đọc)",
    tag: "Chỉ số cơ bản",
    tagColor: "blue",
    content: `
      <p>RSI đo xem <strong>giá đang tăng/giảm quá mức</strong> chưa, thang 0–100.</p>
      <ul>
        <li>📉 <strong>RSI &lt; 30</strong>: Bán quá mức — có thể sắp phục hồi</li>
        <li>📈 <strong>RSI &gt; 70</strong>: Mua quá mức — có thể sắp điều chỉnh</li>
        <li>⚖️ <strong>RSI 40–60</strong>: Vùng bình thường</li>
      </ul>
      <p class="edu-lesson-warning">⚠️ RSI thấp không có nghĩa giá không thể xuống thêm!</p>
    `,
  },
  {
    id: "sr_101",
    title: "Hỗ trợ & Kháng cự là gì?",
    tag: "Phân tích giá",
    tagColor: "green",
    content: `
      <p>Các mức giá mà thị trường đã <strong>phản ứng nhiều lần</strong> trong quá khứ.</p>
      <ul>
        <li>🟢 <strong>Hỗ trợ</strong>: Giá bật lên từ đây — phe mua xuất hiện</li>
        <li>🔴 <strong>Kháng cự</strong>: Giá bị chặn lại — phe bán xuất hiện</li>
      </ul>
      <p class="edu-lesson-tip">💡 Mua gần hỗ trợ, chốt lời gần kháng cự = chiến lược cơ bản nhất.</p>
    `,
  },
  {
    id: "stoploss_101",
    title: "Tại sao cần Stop Loss?",
    tag: "Quản lý rủi ro",
    tagColor: "red",
    content: `
      <p>Stop Loss là <strong>mức giá tự động thoát</strong> khi thua để bảo vệ vốn.</p>
      <p><strong>Ví dụ:</strong> Mua BTC $100,000, đặt SL $97,000 (-3%). Nếu giá về $97,000 → tự thoát, chỉ mất $3,000 thay vì nhiều hơn.</p>
      <p class="edu-lesson-warning">⚠️ Không có Stop Loss = có thể mất 50–90% vốn trong 1 lệnh!</p>
    `,
  },
  {
    id: "rr_101",
    title: "Risk:Reward là gì?",
    tag: "Chiến lược",
    tagColor: "yellow",
    content: `
      <p>Tỷ lệ <strong>mức thua tối đa / mức lời kỳ vọng</strong>.</p>
      <p><strong>Ví dụ:</strong> SL: -3% | TP: +6% → R:R = 1:2 ✅</p>
      <ul>
        <li>✅ <strong>R:R ≥ 1:2</strong>: Tốt — thắng 1 bù 2 lần thua</li>
        <li>⚠️ <strong>R:R = 1:1</strong>: Cần thắng &gt;60% mới có lãi</li>
        <li>❌ <strong>R:R &lt; 1:1</strong>: Thua ngay cả khi thắng nhiều hơn</li>
      </ul>
    `,
  },
  {
    id: "no_trade_101",
    title: "Khi nào KHÔNG nên vào lệnh?",
    tag: "Quan trọng",
    tagColor: "orange",
    content: `
      <ul>
        <li>📰 Sắp có tin tức kinh tế lớn (Fed, CPI...)</li>
        <li>📊 Thị trường đang đi ngang, không có xu hướng rõ</li>
        <li>😰 Bạn đang giao dịch vì sợ bỏ lỡ (FOMO)</li>
        <li>💸 Vừa thua lệnh lớn, muốn "gỡ vốn"</li>
        <li>🌙 Thị trường ít thanh khoản (cuối tuần, đêm khuya)</li>
      </ul>
      <p class="edu-lesson-tip">💡 Không vào lệnh cũng là quyết định giao dịch đúng đắn.</p>
    `,
  },
];
