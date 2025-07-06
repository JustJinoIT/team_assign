# 📦 기본 환경: Python + Streamlit + JSON (로컬 저장)
# 웹 배포: Streamlit Cloud (무료 배포)

import streamlit as st
import json
import os
from collections import defaultdict
import random

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ======== 데이터 파일 경로 ========
PARTICIPANTS_FILE = os.path.join(DATA_DIR, "participants.json")
ARTICLES_FILE = os.path.join(DATA_DIR, "articles.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
ATTENDANCE_FILE = os.path.join(DATA_DIR, "attendance.json")

# ======== 초기 로딩 or 생성 ========
def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

participants = load_json(PARTICIPANTS_FILE, {})
articles = load_json(ARTICLES_FILE, {})
history = load_json(HISTORY_FILE, {})
attendance = load_json(ATTENDANCE_FILE, {})

# ======== UI ========
st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램")
st.caption("7주간, 출결/아티클 기반 자동 조 편성 시스템")

# ---- 참가자 등록 ----
st.header("1. 참가자 등록")
with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submitted = st.form_submit_button("참가자 추가")
    if submitted and pid and name:
        participants[pid] = {"name": name}
        save_json(PARTICIPANTS_FILE, participants)
        st.success(f"✅ {name} 등록 완료")

# ---- 엑셀 업로드로 참가자 등록 ----
st.subheader("📥 엑셀 업로드로 다중 참가자 등록")
uploaded_file = st.file_uploader("참여자 엑셀 파일 업로드", type=["xlsx"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    new_count = 0
    for _, row in df.iterrows():
        pid, name = row["id"], row["name"]
        if pid not in participants:
            participants[pid] = {"name": name}
            new_count += 1
    save_json(PARTICIPANTS_FILE, participants)
    st.success(f"✅ {new_count}명 참가자 등록 완료")
    
# ---- 아티클 등록 ----
st.header("2. 주차별 아티클 등록")
week = st.selectbox("주차 선택", list(range(1, 8)))
with st.form("article_form"):
    cols = st.columns(4)
    article_data = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", key=f"t{i}")
            link = st.text_input(f"{i+1}번 링크", key=f"l{i}")
            article_data.append({"id": chr(65+i), "title": title, "link": link})
    if st.form_submit_button("주차 아티클 저장"):
        articles[str(week)] = article_data
        save_json(ARTICLES_FILE, articles)
        st.success("✅ 저장 완료")

# ---- 출결 등록 ----
st.header("3. 출결 등록")
selected_week = st.selectbox("주차 선택 (출결용)", list(range(1, 8)), key="att_week")
for pid, p in participants.items():
    status = st.radio(f"{p['name']} 출결", ["attending", "absent_pre", "absent_day"], horizontal=True, key=f"att_{pid}")
    attendance.setdefault(str(selected_week), {})[pid] = status
save_json(ATTENDANCE_FILE, attendance)

# ---- 조 편성 ----
st.header("4. 조 자동 배정")
if st.button("해당 주차 조 편성 실행"):
    week = str(selected_week)
    present = [pid for pid, status in attendance[week].items() if status == "attending"]
    random.shuffle(present)

    # 기본조 4~5명으로 구성
    base_groups = [present[i:i+4] for i in range(0, len(present), 4)]
    for g in base_groups:
        if len(g) == 3 and len(present) % 4 != 0:
            g.append(present.pop())  # 예외적 5인조

    # 아티클 활동조 구성
    article_ids = [a['id'] for a in articles[week]]
    activity_groups = {aid: [] for aid in article_ids}
    for pid in present:
        aid = random.choice(article_ids)
        activity_groups[aid].append(pid)

    # 기본조 내 겹치는 아티클 제거 (5인조 예외 허용)
    cleaned_base = []
    for group in base_groups:
        if len(group) <= 4:
            group_articles = [aid for aid, members in activity_groups.items() if any(pid in members for pid in group)]
            if len(set(group_articles)) < len(group):
                continue  # skip badly grouped
        cleaned_base.append(group)

    history[week] = {
        "base_groups": cleaned_base,
        "activity_groups": activity_groups
    }
    save_json(HISTORY_FILE, history)
    st.success(f"✅ {week}주차 조 편성 완료")

# ---- 이력 확인 ----
st.header("5. 주차별 조 편성 이력")
view_week = st.selectbox("확인할 주차 선택", list(history.keys())[::-1], key="hist_view")
if view_week in history:
    st.subheader("📌 기본조")
    for idx, group in enumerate(history[view_week]["base_groups"], 1):
        st.write(f"{idx}조: {', '.join(participants[pid]['name'] for pid in group)}")

    st.subheader("📎 활동조")
    for aid, members in history[view_week]["activity_groups"].items():
        names = ', '.join(participants[pid]['name'] for pid in members)
        title = next((a['title'] for a in articles[view_week] if a['id'] == aid), aid)
        st.write(f"{aid} ({title}): {names}")

# ---- 끝 ----
