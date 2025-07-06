import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import os
from collections import defaultdict
import random

# 화면 너비 시뮬레이션 (실제 환경에선 js 연동 가능)
width = st.sidebar.slider("화면 너비 조절 (시뮬레이션)", 300, 1200, 900)
is_mobile = width < 600

# --- Firebase 초기화 (최초 1회만) ---
if "firebase_app" not in st.session_state:
    cred_path = st.secrets["firebase"]["cred_path"]
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        st.session_state["firebase_app"] = True
    else:
        st.error("Firebase 서비스 계정 키 JSON 경로 오류")
        st.stop()

db = firestore.client()

st.title("Firebase 연동 기본조 + 활동조 배정 프로그램")

# --- 함수들 ---

def add_participant(pid, name):
    db.collection("participants").document(pid).set({"name": name})

def get_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def save_articles(week, article_list):
    db.collection("articles").document(str(week)).set({"articles": article_list})

def get_articles(week):
    doc = db.collection("articles").document(str(week)).get()
    if doc.exists:
        return doc.to_dict().get("articles", [])
    return []

def save_attendance(week, attendance_dict):
    db.collection("attendance").document(str(week)).set(attendance_dict)

def get_attendance(week):
    doc = db.collection("attendance").document(str(week)).get()
    if doc.exists:
        return doc.to_dict()
    return {}

def save_history(week, base_groups, activity_groups):
    db.collection("history").document(str(week)).set({
        "base_groups": base_groups,
        "activity_groups": activity_groups
    })

def get_history(week):
    doc = db.collection("history").document(str(week)).get()
    if doc.exists:
        return doc.to_dict()
    return {}

# --- UI 구성 함수들 ---

def participant_ui():
    if is_mobile:
        st.subheader("참가자 등록")
        pid = st.text_input("고유 ID")
        name = st.text_input("이름")
        if st.button("참가자 추가"):
            if pid and name:
                add_participant(pid, name)
                st.success(f"{name} 등록 완료")
            else:
                st.warning("ID와 이름을 모두 입력하세요")
        if st.button("참가자 목록 불러오기"):
            participants = get_participants()
            st.dataframe(pd.DataFrame(participants).T)
    else:
        col1, col2 = st.columns([2, 3])
        with col1.expander("참가자 등록"):
            pid = st.text_input("고유 ID")
            name = st.text_input("이름")
            if st.button("참가자 추가"):
                if pid and name:
                    add_participant(pid, name)
                    st.success(f"{name} 등록 완료")
                else:
                    st.warning("ID와 이름을 모두 입력하세요")
        with col2.expander("참가자 목록"):
            if st.button("목록 불러오기"):
                participants = get_participants()
                st.dataframe(pd.DataFrame(participants).T)

def excel_upload_ui():
    st.subheader("엑셀 업로드로 참가자 및 조 정보 자동 등록")
    uploaded_file = st.file_uploader("시트 업로드 (xlsx)", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        # 참가자 자동 등록
        if "성명" in df.columns:
            participants = get_participants()
            existing_names = [p["name"] for p in participants.values()]
            count = 0
            for _, row in df.iterrows():
                name = str(row["성명"]).strip()
                if name and name not in existing_names:
                    pid = name.lower().replace(" ", "")
                    add_participant(pid, name)
                    count += 1
            st.success(f"✅ {count}명 참가자 자동 등록 완료")

        # 주차별 출결 및 조 배정 반영 (history 및 attendance)
        for week in range(1, 8):
            col = f"{week}주차"
            if col in df.columns:
                attendance_dict = {}
                base_groups = defaultdict(list)
                for _, row in df.iterrows():
                    name = str(row["성명"]).strip()
                    participants = get_participants()
                    pid = next((k for k, v in participants.items() if v["name"] == name), None)
                    if not pid:
                        continue
                    val = str(row[col]).strip()
                    if val == "불참":
                        attendance_dict[pid] = "absent_pre"
                    elif val == "-":
                        attendance_dict[pid] = "absent_day"
                    elif val.endswith("조"):
                        attendance_dict[pid] = "attending"
                        base_groups[val].append(pid)
                save_attendance(str(week), attendance_dict)
                save_history(str(week), list(base_groups.values()), {})
        st.success("📅 주차별 조 편성 및 출결 정보 시트에서 반영 완료")

def article_ui():
    st.subheader("주차별 아티클 등록")
    week = st.selectbox("주차 선택", list(range(1, 8)))
    article_list = get_articles(week)
    cols = st.columns(4)
    new_articles = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", value=article_list[i]["title"] if i < len(article_list) else "", key=f"title_{week}_{i}")
            link = st.text_input(f"{i+1}번 링크", value=article_list[i]["link"] if i < len(article_list) else "", key=f"link_{week}_{i}")
            new_articles.append({"id": chr(65 + i), "title": title, "link": link})
    if st.button("아티클 저장"):
        save_articles(week, new_articles)
        st.success("✅ 아티클 저장 완료")

def attendance_ui():
    st.subheader("출결 등록")
    week = st.selectbox("출결 주차 선택", list(range(1, 8)))
    participants = get_participants()
    attendance_dict = get_attendance(week)

    for pid, p in participants.items():
        status = attendance_dict.get(pid, "attending")
        if is_mobile:
            st.write(p["name"])
            status = st.radio(f"출결 선택", ["attending", "absent_pre", "absent_day"], index=["attending", "absent_pre", "absent_day"].index(status), key=f"att_{week}_{pid}")
        else:
            cols = st.columns([3, 5])
            with cols[0]:
                st.write(p["name"])
            with cols[1]:
                status = st.radio("", ["attending", "absent_pre", "absent_day"], index=["attending", "absent_pre", "absent_day"].index(status), horizontal=True, key=f"att_{week}_{pid}")
        attendance_dict[pid] = status
    if st.button("출결 저장"):
        save_attendance(week, attendance_dict)
        st.success("✅ 출결 저장 완료")

def assign_groups_ui():
    st.subheader("자동 조 편성")
    week = st.selectbox("조 편성 주차 선택", list(range(1, 8)), key="assign_week")
    if st.button("조 편성 실행"):
        attendance_dict = get_attendance(week)
        present = [pid for pid, status in attendance_dict.items() if status == "attending"]
        random.shuffle(present)

        # 기본조 4~5명 구성
        base_groups = [present[i:i + 4] for i in range(0, len(present), 4)]
        for g in base_groups:
            if len(g) == 3 and len(present) % 4 != 0:
                g.append(present.pop())

        # 아티클 활동조 배정
        article_list = get_articles(week)
        article_ids = [a['id'] for a in article_list]
        activity_groups = {aid: [] for aid in article_ids}
        for pid in present:
            aid = random.choice(article_ids)
            activity_groups[aid].append(pid)

        # 기본조 내 아티클 겹침 검사 (5인조 제외)
        cleaned_base = []
        for group in base_groups:
            if len(group) <= 4:
                group_articles = []
                for aid, members in activity_groups.items():
                    if any(pid in members for pid in group):
                        group_articles.append(aid)
                if len(set(group_articles)) < len(group):
                    st.warning(f"조 편성에서 아티클 중복 발견: {', '.join(group)}")
            cleaned_base.append(group)

        save_history(week, cleaned_base, activity_groups)
        st.success(f"✅ {week}주차 조 편성 완료")

def history_ui():
    st.subheader("조 편성 및 출결 이력 확인")
    weeks = [str(i) for i in range(1, 8)]
    week = st.selectbox("확인할 주차 선택", weeks)
    history = get_history(week)
    participants = get_participants()
    if not history:
        st.info("해당 주차 이력 없음")
        return

    st.markdown("### 기본조")
    for idx, group in enumerate(history.get("base_groups", []), 1):
        names = [participants[pid]["name"] if pid in participants else pid for pid in group]
        st.write(f"{idx}조: {', '.join(names)}")

    st.markdown("### 활동조")
    for aid, members in history.get("activity_groups", {}).items():
        title = ""
        articles = get_articles(week)
        for a in articles:
            if a["id"] == aid:
                title = a["title"]
                break
        names = [participants[pid]["name"] if pid in participants else pid for pid in members]
        st.write(f"{aid} ({title}): {', '.join(names)}")

# --- 메인 화면 UI 구성 ---

if is_mobile:
    st.write("📱 모바일 UI 모드")

    participant_ui()
    st.markdown("---")
    excel_upload_ui()
    st.markdown("---")
    article_ui()
    st.markdown("---")
    attendance_ui()
    st.markdown("---")
    assign_groups_ui()
    st.markdown("---")
    history_ui()
else:
    st.write("💻 PC UI 모드")

    st.sidebar.header("메뉴")
    menu = st.sidebar.radio("기능 선택", [
        "참가자 등록/목록",
        "엑셀 업로드",
        "아티클 등록",
        "출결 등록",
        "조 편성",
        "이력 확인"
    ])

    if menu == "참가자 등록/목록":
        participant_ui()
    elif menu == "엑셀 업로드":
        excel_upload_ui()
    elif menu == "아티클 등록":
        article_ui()
    elif menu == "출결 등록":
        attendance_ui()

    st.success("📅 주차별 조 편성까지 자동 반영 완료")
