import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
import random
import pandas as pd

# ==== Firebase 초기화 ====
if not firebase_admin._apps:
    service_account_info = json.loads(st.secrets["firebase"]["service_account_json"])
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==== 함수들 ====

def load_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def load_articles():
    docs = db.collection("articles").stream()
    result = defaultdict(list)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        if week:
            result[str(week)].append(data)
    return dict(result)

def load_history():
    docs = db.collection("history").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def load_attendance():
    docs = db.collection("attendance").stream()
    result = defaultdict(dict)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        pid = data.get("participant_id")
        status = data.get("status")
        if week and pid:
            result[str(week)][pid] = status
    return dict(result)

# ==== 참가자 등록 및 관리 ====

st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (Firebase 연동)")

st.header("1. 참가자 등록 및 관리")

with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submit = st.form_submit_button("등록")
    if submit and pid and name:
        db.collection("participants").document(pid).set({"name": name})
        st.success(f"✅ {name} 참가자 등록 완료")

st.subheader("참가자 리스트 (삭제 가능)")

participants = load_participants()
for pid, pdata in participants.items():
    col1, col2 = st.columns([4,1])
    with col1:
        st.text(f"{pdata.get('name', '')} ({pid})")
    with col2:
        if st.button("삭제", key=f"del_{pid}"):
            db.collection("participants").document(pid).delete()
            st.experimental_rerun()

# 엑셀 업로드 기능 (선택 사항)
st.subheader("📥 엑셀 업로드 (중복 등록 방지 및 출결/기본조 반영)")
uploaded_file = st.file_uploader("엑셀(.xlsx) 업로드", type=["xlsx"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    for _, row in df.iterrows():
        name = str(row.get("성명", "")).strip()
        if name:
            pid = name.lower().replace(" ", "")
            if pid not in participants:
                db.collection("participants").document(pid).set({"name": name})
    st.success("✅ 엑셀 참가자 등록 완료. 새로고침 해주세요.")

# ==== 주차 선택 (모든 관리 기능 공통) ====

st.header("2. 주차별 관리")

weeks_all = list(range(1, 8))
selected_week = st.selectbox("주차 선택", weeks_all)

# ==== 2-1. 아티클 등록 및 현황 ====

st.subheader(f"2-1. {selected_week}주차 아티클 등록 및 현황")

with st.form("article_form"):
    articles = load_articles()
    week_articles = articles.get(str(selected_week), [])
    # 기존 아티클 데이터 불러오기
    existing_titles = {art['id']: art.get('title', '') for art in week_articles}
    existing_links = {art['id']: art.get('link', '') for art in week_articles}

    cols = st.columns(4)
    article_data = []
    for i in range(4):
        art_id = str(i+1)
        with cols[i]:
            title = st.text_input(f"{art_id}번 제목", value=existing_titles.get(art_id, ""), key=f"art_title_{art_id}")
            link = st.text_input(f"{art_id}번 링크", value=existing_links.get(art_id, ""), key=f"art_link_{art_id}")
            article_data.append({"week": str(selected_week), "id": art_id, "title": title, "link": link})

    if st.form_submit_button("아티클 저장"):
        # 기존 아티클 삭제
        arts = db.collection("articles").where("week", "==", str(selected_week)).stream()
        for doc in arts:
            doc.reference.delete()
        # 새로 저장
        for art in article_data:
            if art["title"].strip():  # 빈 제목은 저장 안 함
                db.collection("articles").add(art)
        st.success("✅ 아티클 저장 완료")

# ==== 2-2. 출결 등록 및 현황 ====

st.subheader(f"2-2. {selected_week}주차 출결 등록 및 현황")

attendance_data = load_attendance()
attendance_week = attendance_data.get(str(selected_week), {})

# 출결 상태: attending, absent_pre, absent_day
# UI는 불참자 및 당일 불참 체크박스, 출석은 체크 안함

participants = load_participants()

# 기존 출결 상태 불러와서 체크박스에 반영
st.markdown("⛔️ 불참자 또는 당일 불참자만 체크하세요 (출석자는 체크할 필요 없음)")
cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    status = attendance_week.get(pid, "attending")
    is_absent_pre = (status == "absent_pre")
    is_absent_day = (status == "absent_day")
    # 두 체크박스 중복 방지 UI 처리
    absent_pre_chk = col.checkbox(f"{pdata['name']} (불참)", key=f"absent_pre_{selected_week}_{pid}", value=is_absent_pre)
    absent_day_chk = col.checkbox(f"{pdata['name']} (당일불참)", key=f"absent_day_{selected_week}_{pid}", value=is_absent_day)
    # 출석 기본값 처리
    if absent_pre_chk and absent_day_chk:
        # 둘 다 체크 불가, 우선 당일불참 유지, 불참 체크 해제
        st.session_state[f"absent_pre_{selected_week}_{pid}"] = False
        absent_pre_chk = False

if st.button("✅ 출결 저장"):
    for pid in participants:
        absent_pre = st.session_state.get(f"absent_pre_{selected_week}_{pid}", False)
        absent_day = st.session_state.get(f"absent_day_{selected_week}_{pid}", False)
        if absent_pre:
            status = "absent_pre"
        elif absent_day:
            status = "absent_day"
        else:
            status = "attending"
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("✅ 출결 저장 완료")

# ==== 3. 조 배정 실행 및 재실행 ====

st.header(f"3. {selected_week}주차 조 배정")

history = load_history()
# 이력 중 해당 주차만 필터
week_history = {hid:h for hid,h in history.items() if h.get('week') == str(selected_week)}

base_group_exists = any('base_group' in h for h in week_history.values())

def assign_groups(selected_week):
    attendance = load_attendance()
    participants = load_participants()
    articles = load_articles()

    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    if not present:
        st.warning("출석한 참가자가 없습니다.")
        return None, None

    random.shuffle(present)

    # 기본조 최대 4명 우선, 5명도 허용
    def split_base_groups(present):
        n = len(present)
        min_groups = max(1, n // 4)
        max_groups = min(6, n // 3)  # 최대 6개 조 제한
        for g in range(min_groups, max_groups+1):
            size = n // g
            rem = n % g
            if size == 4 or (size == 3 and rem == 0):
                groups = []
                idx = 0
                for i in range(g):
                    group_size = size + (1 if i < rem else 0)
                    groups.append(present[idx:idx+group_size])
                    idx += group_size
                return groups
        # 기본 4명씩 배정
        groups = [present[i:i+4] for i in range(0, n, 4)]
        # 마지막 3명 조면 5명 조로 합치기
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)

    # 활동조: 아티클 4개 기준 배정 (1,2,3,4)
    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list if a['title'].strip() != ""]
    if len(article_ids) < 4:
        article_ids = ['1','2','3','4']  # 기본값

    activity_groups = {aid: [] for aid in article_ids}
    base_to_activity = {}

    for group in base_groups:
        assigned_articles = set()
        base_to_activity_group = {}
        for i, pid in enumerate(group):
            if len(group) == 4:
                aid = article_ids[i]
            else:
                aid = random.choice(article_ids)
            base_to_activity_group[pid] = aid
            assigned_articles.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(base_to_activity_group)

    return base_groups, activity_groups, base_to_activity

if base_group_exists:
    if st.button("🔄 조 배정 재실행"):
        base_groups, activity_groups, base_to_activity = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조 배정할 수 없습니다.")
        else:
            # 기존 이력 삭제
            for doc in db.collection("history").where("week", "==", str(selected_week)).stream():
                doc.reference.delete()
            # 새로 저장
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, members in activity_groups.items():
                for pid in members:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success(f"{selected_week}주차 조 배정 재실행 완료")
else:
    if st.button("🚀 조 배정 실행"):
        base_groups, activity_groups, base_to_activity = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조 배정할 수 없습니다.")
        else:
            for doc in db.collection("history").where("week", "==", str(selected_week)).stream():
                doc.reference.delete()
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, members in activity_groups.items():
                for pid in members:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success(f"{selected_week}주차 조 배정 완료")

# ==== 4. 조 배정 이력 확인 ====

st.header(f"4. {selected_week}주차 조 배정 이력 확인")

history = load_history()
participants = load_participants()

week_histories = {hid:h for hid,h in history.items() if h.get('week') == str(selected_week)}

base_group_members = defaultdict(list)
activity_group_members = defaultdict(list)

# 참가자별 아티클 매핑
participant_to_article = {}

for h in week_histories.values():
    pid = h.get('participant_id')
    if 'base_group' in h:
        base_group_members[h['base_group']].append(pid)
    if 'activity_group' in h:
        activity_group_members[h['activity_group']].append(pid)
        participant_to_article[pid] = h['activity_group']

st.subheader("기본조")
for bg in sorted(base_group_members.keys()):
    members = base_group_members[bg]
    names = []
    for pid in members:
        name = participants.get(pid, {}).get('name', pid)
        art = participant_to_article.get(pid, "")
        names.append(f"{name}({art})" if art else name)
    st.write(f"{bg}: {', '.join(names)}")

st.subheader("활동조")
for ag in sorted(activity_group_members.keys()):
    members = activity_group_members[ag]
    names = [participants.get(pid, {}).get('name', pid) for pid in members]
    st.write(f"{ag}: {', '.join(names)}")

