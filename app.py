import os
import sys
import pickle
import pandas as pd
import numpy as np
import xgboost as xgb
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Add src to system path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from ml_pipeline.processing import process_data, categorical_cols, cts_cols, map_month_to_quarter
from ml_pipeline.utils import split_and_encode_data, drop_cols
from ml_pipeline.drift import pred_cat_cols, pred_cts_cols, preprocess_steps

# Set Page Configuration
st.set_page_config(
    page_title="Telecom Churn Intelligence Platform",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(90deg, #1E88E5 0%, #1565C0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #555;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 20px;
        border-left: 5px solid #1E88E5;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .stAlert {
        border-radius: 8px;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Helper Functions to Load Artifacts
@st.cache_resource
def load_models():
    base_model_path = os.path.join(os.path.dirname(__file__), 'models/xgb_base.model')
    retrained_model_path = os.path.join(os.path.dirname(__file__), 'models/xgb_retrained.model')
    
    base_model = xgb.Booster()
    retrained_model = xgb.Booster()
    
    if os.path.exists(base_model_path):
        base_model.load_model(base_model_path)
    if os.path.exists(retrained_model_path):
        retrained_model.load_model(retrained_model_path)
        
    return base_model, retrained_model

@st.cache_resource
def load_transformers():
    encoder_path = os.path.join(os.path.dirname(__file__), 'data/raw/encoder.pkl')
    scaler_path = os.path.join(os.path.dirname(__file__), 'data/raw/scaler.pkl')
    
    encoder = None
    scaler = None
    if os.path.exists(encoder_path):
        with open(encoder_path, 'rb') as f:
            encoder = pickle.load(f)
    if os.path.exists(scaler_path):
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
            
    return encoder, scaler

# Load Data and Models
base_model, retrained_model = load_models()
encoder, scaler = load_transformers()
encoded_features = list(encoder.get_feature_names_out(categorical_cols)) if encoder else []

# Sidebar Navigation
st.sidebar.image("https://images.unsplash.com/photo-1584438784894-089d6a62b8fa?w=400&q=80", use_container_width=True)
st.sidebar.title("📡 Churn Navigation")
app_mode = st.sidebar.radio(
    "Select Module:",
    ["📊 Executive Dashboard", "👤 Individual Churn Predictor", "📁 Batch Prediction & Analysis", "🔄 MLOps & Drift Monitoring"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Model Configuration")
selected_model_name = st.sidebar.selectbox(
    "Active Prediction Engine:",
    ["Retrained Model (Continuous Feedback)", "Base XGBoost Model"]
)
active_model = retrained_model if "Retrained" in selected_model_name else base_model

st.sidebar.info(
    "**Project Context**: Telecom customer churn prediction with Deepchecks drift monitoring and automated retraining feedback loops."
)

# ---------------------------------------------------------
# MODULE 1: EXECUTIVE DASHBOARD
# ---------------------------------------------------------
if app_mode == "📊 Executive Dashboard":
    st.markdown('<div class="main-header">Telecom Churn Executive Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Overview of Machine Learning Model Evolution, Performance Gain & Business Metrics</div>', unsafe_allow_html=True)
    
    # Top KPI Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Base Model Recall", value="43.18%", delta="Initial baseline")
    with col2:
        st.metric(label="Retrained Model Recall", value="74.90%", delta="+31.72% Gain", delta_color="normal")
    with col3:
        st.metric(label="Retrained F1 Score", value="0.688", delta="+0.199 Gain", delta_color="normal")
    with col4:
        st.metric(label="Model ROC AUC", value="0.855", delta="High Discrimination")
        
    st.markdown("---")
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("🎯 Base vs. Retrained Model Recall Comparison")
        metrics_df = pd.DataFrame({
            "Metric": ["Recall", "F1 Score", "AUC"],
            "Base Model": [0.4318, 0.4891, 0.6796],
            "Retrained Feedback Model": [0.7490, 0.6884, 0.8554]
        })
        fig = px.bar(
            metrics_df.melt(id_vars="Metric", var_name="Model", value_name="Score"),
            x="Metric", y="Score", color="Model", barmode="group",
            text_auto=".3f",
            color_discrete_sequence=["#90A4AE", "#1E88E5"],
            title="Performance Metrics Improvement After Drift Retraining"
        )
        fig.update_layout(yaxis_range=[0, 1.0])
        st.plotly_chart(fig, use_container_width=True)
        
    with col_right:
        st.subheader("📉 Churn Rate by Customer Satisfaction Score")
        data_path = os.path.join(os.path.dirname(__file__), 'data/processed/processed_churn_data.csv')
        if os.path.exists(data_path):
            sample_df = pd.read_csv(data_path).head(1000)
            if 'Satisfaction Score' in sample_df.columns and 'Churn Value' in sample_df.columns:
                sat_df = sample_df.groupby('Satisfaction Score')['Churn Value'].mean().reset_index()
                sat_df['Churn %'] = sat_df['Churn Value'] * 100
                fig_sat = px.line(
                    sat_df, x='Satisfaction Score', y='Churn %', markers=True,
                    title="Churn Probability vs Satisfaction Score",
                    color_discrete_sequence=["#E53935"]
                )
                st.plotly_chart(fig_sat, use_container_width=True)
        else:
            st.info("Run `python3 src/engine.py` to generate processed data visualization.")
            
    st.markdown("---")
    st.markdown("### 💡 Business Impact Summary")
    st.success(
        "**Key takeaway**: Monitoring data and model drift allows telecommunication operators to catch shifting customer behavior. "
        "By feeding misclassified churn instances back into training rounds, model recall jumped from **43.2% to 74.9%**, successfully capturing ~31% more at-risk subscribers!"
    )

# ---------------------------------------------------------
# MODULE 2: INDIVIDUAL CHURN PREDICTOR
# ---------------------------------------------------------
elif app_mode == "👤 Individual Churn Predictor":
    st.markdown('<div class="main-header">Individual Customer Churn Predictor</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Calculate real-time churn probability for a specific customer profile</div>', unsafe_allow_html=True)
    
    with st.form("customer_profile_form"):
        st.subheader("1. Demographics & Account Info")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            gender = st.selectbox("Gender", ["Female", "Male", "Not Specified", "Other"])
            married = st.selectbox("Married", ["Yes", "No", "Not Specified"])
        with c2:
            age = st.number_input("Age", min_value=18, max_value=100, value=38)
            dependents = st.selectbox("Dependents", ["No", "Yes", "Not Specified"])
        with c3:
            num_dependents = st.number_input("Number of Dependents", min_value=0, max_value=10, value=0)
            num_referrals = st.number_input("Number of Referrals", min_value=0, max_value=20, value=1)
        with c4:
            referred_friend = st.selectbox("Referred a Friend", ["Yes", "No"])
            offer = st.selectbox("Offer Type", ["No Offer", "offer_A", "offer_B", "offer_C", "offer_D", "offer_E"])
            
        st.subheader("2. Telecom & Data Services")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            phone_service = st.selectbox("Phone Service", ["Yes", "No"])
            multiple_lines = st.selectbox("Multiple Lines", ["No", "Yes", "None"])
        with s2:
            internet_service = st.selectbox("Internet Service", ["Yes", "No"])
            internet_type = st.selectbox("Internet Type", ["Fiber Optic", "DSL", "Cable", "None", "Not Applicable"])
        with s3:
            online_security = st.selectbox("Online Security", ["No", "Yes"])
            online_backup = st.selectbox("Online Backup", ["No", "Yes"])
        with s4:
            tech_support = st.selectbox("Premium Tech Support", ["No", "Yes"])
            streaming_tv = st.selectbox("Streaming TV", ["No", "Yes"])

        st.subheader("3. Usage, Charges & Satisfaction")
        u1, u2, u3, u4 = st.columns(4)
        with u1:
            total_rech_amt = st.number_input("Total Recharge Amount ($)", min_value=0.0, value=250.0)
            total_rech_data = st.number_input("Total Recharge Data ($)", min_value=0.0, value=50.0)
        with u2:
            arpu = st.number_input("Average Revenue Per User (ARPU)", min_value=0.0, value=65.0)
            arpu_4g = st.number_input("4G ARPU", min_value=0.0, value=20.0)
            arpu_5g = st.number_input("5G ARPU", min_value=0.0, value=0.0)
        with u3:
            vol_4g = st.number_input("4G Data Volume (GB)", min_value=0.0, value=15.0)
            vol_5g = st.number_input("5G Data Volume (GB)", min_value=0.0, value=0.0)
        with u4:
            satisfaction_score = st.slider("Satisfaction Score (1 = Low, 5 = High)", 1, 5, 2)
            payment_method = st.selectbox("Payment Method", ["Bank Withdrawal", "Credit Card", "Wallet Balance"])
            
        submit_btn = st.form_submit_button("🔮 Predict Churn Risk", use_container_width=True)

    if submit_btn:
        # Build single row dataframe matching feature structure
        customer_dict = {
            'Gender': gender, 'Married': married, 'Dependents': dependents, 'offer': offer,
            'Referred a Friend': referred_friend, 'Phone Service': phone_service,
            'Multiple Lines': multiple_lines, 'Internet Service': internet_service,
            'Internet Type': internet_type, 'Online Security': online_security,
            'Online Backup': online_backup, 'Device Protection Plan': 'No',
            'Premium Tech Support': tech_support, 'Streaming TV': streaming_tv,
            'Streaming Movies': 'No', 'Streaming Music': 'No', 'Unlimited Data': 'Yes',
            'Payment Method': payment_method,
            'Age': age, 'Number of Dependents': num_dependents, 'roam_ic': 0.0, 'roam_og': 0.0,
            'loc_og_t2t': 10.0, 'loc_og_t2m': 15.0, 'loc_og_t2f': 0.0, 'loc_og_t2c': 0.0,
            'std_og_t2t': 5.0, 'std_og_t2m': 10.0, 'std_og_t2f': 0.0, 'std_og_t2c': 0.0,
            'isd_og': 0.0, 'spl_og': 0.0, 'og_others': 0.0, 'loc_ic_t2t': 5.0, 'loc_ic_t2m': 10.0,
            'loc_ic_t2f': 0.0, 'std_ic_t2t': 0.0, 'std_ic_t2m': 0.0, 'std_ic_t2f': 0.0,
            'std_ic_t2o': 0.0, 'spl_ic': 0.0, 'isd_ic': 0.0, 'ic_others': 0.0,
            'total_rech_amt': total_rech_amt, 'total_rech_data': total_rech_data,
            'vol_4g': vol_4g, 'vol_5g': vol_5g, 'arpu_5g': arpu_5g, 'arpu_4g': arpu_4g,
            'arpu': arpu, 'aug_vbc_5g': 0.0, 'Number of Referrals': num_referrals,
            'Streaming Data Consumption': 5.0, 'Satisfaction Score': satisfaction_score,
            'total_recharge': total_rech_amt + total_rech_data
        }
        
        single_df = pd.DataFrame([customer_dict])
        
        # One-hot encode & scale
        encoded_single = pd.DataFrame(encoder.transform(single_df[categorical_cols]), columns=encoded_features)
        scaled_cts = pd.DataFrame(scaler.transform(single_df[cts_cols]), columns=cts_cols)
        
        processed_single = pd.concat([scaled_cts, encoded_single], axis=1)
        # Reorder to match model expected feature order
        all_predictors = pred_cts_cols + pred_cat_cols
        for col in all_predictors:
            if col not in processed_single.columns:
                processed_single[col] = 0.0
        processed_single = processed_single[all_predictors]
        
        # Predict
        dmatrix_single = xgb.DMatrix(processed_single)
        churn_pred = active_model.predict(dmatrix_single)[0]
        
        st.markdown("---")
        st.subheader("🎯 Prediction Results")
        
        res_col1, res_col2 = st.columns([1, 2])
        with res_col1:
            if churn_pred == 1:
                st.error("🚨 **HIGH RISK OF CHURN**")
                st.markdown("### Status: Customer Likely to Churn")
            else:
                st.success("🟢 **LOW CHURN RISK**")
                st.markdown("### Status: Customer Likely to Stay")
                
        with res_col2:
            st.markdown("#### 🔍 Recommended Business Actions:")
            if churn_pred == 1:
                st.write("- 🎁 **Offer Retention Incentive**: Apply Offer A or upgrade internet package.")
                st.write("- 🛠️ **Dedicated Support**: Contact customer regarding satisfaction score feedback.")
                st.write("- 💳 **Payment Discount**: Suggest auto-withdrawal or promotional monthly discount.")
            else:
                st.write("- ⭐ **Upsell Opportunity**: Recommend 5G data upgrades or premium family packages.")
                st.write("- 🤝 **Referral Program**: Invite customer to refer friends for bill credits.")

# ---------------------------------------------------------
# MODULE 3: BATCH PREDICTION & ANALYSIS
# ---------------------------------------------------------
elif app_mode == "📁 Batch Prediction & Analysis":
    st.markdown('<div class="main-header">Batch Customer Churn Scoring</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Upload subscriber dataset or select sample to score churn risks at scale</div>', unsafe_allow_html=True)
    
    data_source = st.radio("Select Data Source:", ["Use Processed Customer Data", "Upload Custom CSV File"], inline=True)
    
    batch_df = None
    if data_source == "Use Processed Customer Data":
        proc_file = os.path.join(os.path.dirname(__file__), 'data/processed/processed_churn_data.csv')
        if os.path.exists(proc_file):
            batch_df = pd.read_csv(proc_file).head(500)
            st.success(f"Loaded {len(batch_df)} rows from processed dataset.")
        else:
            st.warning("Processed CSV file not found. Run `python3 src/engine.py` first.")
    else:
        uploaded_file = st.file_uploader("Upload Telecom CSV Data", type=["csv"])
        if uploaded_file:
            batch_df = pd.read_csv(uploaded_file)
            st.success(f"Uploaded CSV with {len(batch_df)} rows.")

    if batch_df is not None and st.button("🚀 Run Batch Prediction", use_container_width=True):
        with st.spinner("Scoring customer churn risks..."):
            try:
                # Preprocess batch
                inf_features = preprocess_steps(batch_df, encoded_features, encoder, scaler)
                all_predictors = pred_cts_cols + pred_cat_cols
                for col in all_predictors:
                    if col not in inf_features.columns:
                        inf_features[col] = 0.0
                inf_features = inf_features[all_predictors]
                
                dmatrix_batch = xgb.DMatrix(inf_features)
                batch_preds = active_model.predict(dmatrix_batch)
                
                output_df = batch_df.copy()
                output_df['Predicted_Churn'] = batch_preds
                output_df['Churn_Label'] = output_df['Predicted_Churn'].map({1: 'Churn Risk', 0: 'Retained'})
                
                churn_count = (output_df['Predicted_Churn'] == 1).sum()
                churn_pct = (churn_count / len(output_df)) * 100
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Processed", f"{len(output_df):,}")
                c2.metric("Predicted At-Risk Churn", f"{churn_count:,}")
                c3.metric("Predicted Churn Rate", f"{churn_pct:.1f}%")
                
                st.markdown("### 📊 Churn Distribution")
                fig_batch = px.pie(
                    output_df, names='Churn_Label', title="Predicted Churn Segment Breakdown",
                    color='Churn_Label', color_discrete_map={'Churn Risk': '#E53935', 'Retained': '#43A047'}
                )
                st.plotly_chart(fig_batch, use_container_width=True)
                
                st.markdown("### 📋 Customer Predictions Table")
                st.dataframe(output_df.head(100), use_container_width=True)
                
                csv_data = output_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "📥 Download Scored Batch CSV",
                    data=csv_data,
                    file_name="churn_predictions_scored.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error during batch scoring: {e}")

# ---------------------------------------------------------
# MODULE 4: MLOPS & DRIFT MONITORING
# ---------------------------------------------------------
elif app_mode == "🔄 MLOps & Drift Monitoring":
    st.markdown('<div class="main-header">MLOps Data & Model Drift Monitoring</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Continuous Model Monitoring with Deepchecks & Automated Feedback Loops</div>', unsafe_allow_html=True)
    
    st.info(
        "**Deepchecks Drift Architecture**: Detects covariate feature drift and concept label drift across incoming quarters. "
        "When drift threshold or performance decay is detected, misclassified instances are automatically routed to the feedback retraining loop."
    )
    
    report_dir = os.path.join(os.path.dirname(__file__), 'reports')
    if os.path.exists(report_dir):
        reports = [f for f in os.listdir(report_dir) if f.endswith('.html')]
        st.subheader("📄 Available Deepchecks HTML Reports")
        if reports:
            selected_report = st.selectbox("Select Report to View:", reports)
            report_path = os.path.join(report_dir, selected_report)
            with open(report_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            st.components.v1.html(html_content, height=700, scrolling=True)
        else:
            st.warning("No HTML reports found in `reports/`. Run `python3 src/engine.py` to generate reports.")
    else:
        st.warning("Reports directory not found.")
        
    st.markdown("---")
    st.subheader("⚡ Execute Live Pipeline Retraining")
    st.write("Trigger full execution of `src/engine.py` to run drift monitoring and update model weights with feedback data.")
    
    if st.button("▶️ Execute Pipeline & Update Retrained Model", use_container_width=True):
        with st.spinner("Running MLOps pipeline..."):
            import subprocess
            res = subprocess.run([sys.executable, "src/engine.py"], capture_output=True, text=True)
            if res.returncode == 0:
                st.success("Pipeline executed successfully! Retrained model saved to `models/xgb_retrained.model`.")
                st.text_area("Pipeline Console Logs:", res.stdout, height=250)
            else:
                st.error("Pipeline execution failed:")
                st.text_area("Error Console Output:", res.stderr, height=250)
