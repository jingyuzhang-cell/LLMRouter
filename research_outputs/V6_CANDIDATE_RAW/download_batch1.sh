#!/bin/bash
cd /root/research_outputs/V6_CANDIDATE_RAW

# 1. 美尚生态 300495
wget -q -c -O MS_penalty_notice_2023.pdf "https://static.cninfo.com.cn/finalpage/2023-04-11/1216373883.PDF" &
wget -q -c -O MS_2023_H1.pdf "https://static.cninfo.com.cn/finalpage/2023-08-29/1217682939.PDF" &

# 2. 新海宜 002089
wget -q -c -O XHY_risk_2024.pdf "https://static.cninfo.com.cn/finalpage/2024-01-19/1222686801.PDF" &
wget -q -c -O XHY_suspend_2024.pdf "https://static.cninfo.com.cn/finalpage/2024-02-06/1222880617.PDF" &
wget -q -c -O XHY_delist_2024.pdf "https://static.cninfo.com.cn/finalpage/2024-03-19/1223307111.PDF" &

# 3. 柏堡龙 002776
wget -q -c -O BBL_penalty_2022.pdf "https://static.cninfo.com.cn/finalpage/2022-04-20/1212837292.PDF" &
wget -q -c -O BBL_risk_2022.pdf "https://static.cninfo.com.cn/finalpage/2022-05-05/1212972838.PDF" &

# 4. 鹏博士 600804 (上交所)
wget -q -c -O PBS_letter_2025.pdf "https://static.cninfo.com.cn/finalpage/2025-04-30/1225149212.PDF" &
wget -q -c -O PBS_delist_2025.pdf "https://static.cninfo.com.cn/finalpage/2025-05-31/1225375294.PDF" &
wget -q -c -O PBS_penalty_2025.pdf "https://static.cninfo.com.cn/finalpage/2025-06-06/1225438059.PDF" &

wait
echo "Download batch 1 complete"
find . -name "*.pdf" -size +0 -exec ls -lh {} \;
echo "---"
find . -name "*.pdf" -size 0 -echo "EMPTY: {}" \; 2>/dev/null
