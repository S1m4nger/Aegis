#!/usr/bin/env python3
"""Generate bounded regression suites, run them, record evidence, clean manifest."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
"services/orchestrator/internal/transport/zz_ephemeral_test.go": r'''package transport
import (
 "context"
 "errors"
 "net/http"
 "net/http/httptest"
 "strings"
 "testing"
 "aegis/orchestrator/internal/config"
 "aegis/orchestrator/internal/domain"
 "aegis/orchestrator/internal/orchestrator"
 "aegis/orchestrator/internal/policy"
 "aegis/orchestrator/internal/rules"
 "go.uber.org/zap"
)
type scorer struct { fail bool }
func (s scorer) Ready(context.Context)bool{return !s.fail}
func (s scorer) Score(context.Context,domain.Transaction)(domain.MLSignal,error){
 if s.fail{return domain.MLSignal{},errors.New("down")}
 return domain.MLSignal{Score:.1,ModelVersion:"test",Semantics:"risk_score"},nil
}
func router(t *testing.T, failed bool)http.Handler{
 t.Helper()
 e,err:=rules.New(config.Config{RulesPath:"../../../../configs/rules.json"});if err!=nil{t.Fatal(err)}
 p,err:=policy.Load(config.Config{PolicyPath:"../../../../configs/policy.json"});if err!=nil{t.Fatal(err)}
 return NewRouter(orchestrator.New(scorer{failed},e,p),zap.NewNop())
}
func TestTransportContracts(t *testing.T){
 h:=router(t,false)
 for _,body:=range []string{`{}`,`null`,`{"step":1,"type":"TRANSFER"}`,`{"step":1,"type":"TRANSFER","amount":null}`,`{"step":1,"type":"TRANSFER","amount":-1}`,`{"step":1,"type":"TRANSFER","amount":0,"isFraud":1}`,`{"step":1.2,"type":"TRANSFER","amount":0}`,`{"step":1,"type":"UNKNOWN","amount":0}`,`{"step":1,"type":"TRANSFER","amount":0} {}`,strings.Repeat(" ",65537)+`{}`} {
  w:=httptest.NewRecorder(); h.ServeHTTP(w,httptest.NewRequest("POST","/v1/analyze",strings.NewReader(body)))
  if w.Code!=400{t.Errorf("body %q: status %d",body[:min(100,len(body))],w.Code)}
 }
 w:=httptest.NewRecorder();h.ServeHTTP(w,httptest.NewRequest("POST","/v1/analyze",strings.NewReader(`{"step":1,"type":"TRANSFER","amount":0}`)))
 if w.Code!=200||!strings.Contains(w.Body.String(),"test"){t.Fatalf("%d %s",w.Code,w.Body.String())}
}
func TestPanicJSON(t *testing.T){
 h:=recoverJSON(zap.NewNop())(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){panic("sensitive internals")}))
 w:=httptest.NewRecorder();h.ServeHTTP(w,httptest.NewRequest("GET","/",nil));if w.Code!=500||w.Header().Get("Content-Type")!="application/json"||strings.Contains(w.Body.String(),"sensitive"){t.Fatal(w.Code,w.Body.String())}
}
func TestUnavailableScorer(t *testing.T){
 h:=router(t,true)
 for _,path:=range []string{"/health/ready","/v1/analyze"}{
  method:="GET";if path=="/v1/analyze"{method="POST"}
  w:=httptest.NewRecorder();h.ServeHTTP(w,httptest.NewRequest(method,path,strings.NewReader(`{"step":1,"type":"TRANSFER","amount":1}`)))
  if w.Code!=503{t.Fatalf("%s %d",path,w.Code)}
 }
 w:=httptest.NewRecorder();h.ServeHTTP(w,httptest.NewRequest("GET","/health/live",nil));if w.Code!=200{t.Fatal(w.Code)}
}
''',
"services/orchestrator/internal/mlclient/zz_ephemeral_test.go": r'''package mlclient
import("context";"io";"net/http";"strings";"testing";"aegis/orchestrator/internal/domain")
type roundTrip func(*http.Request)(*http.Response,error)
func(f roundTrip)RoundTrip(r *http.Request)(*http.Response,error){return f(r)}
func client(body string)*Client{return &Client{url:"http://scorer",http:&http.Client{Transport:roundTrip(func(r *http.Request)(*http.Response,error){return &http.Response{StatusCode:200,Body:io.NopCloser(strings.NewReader(body)),Header:make(http.Header)},nil})}}}
func TestRejectMalformedScore(t *testing.T){
 for _,body:=range []string{`{}`,`{"score":null,"model_version":"v","score_semantics":"risk"}`,`{"score":-1,"model_version":"v","score_semantics":"risk"}`,`{"score":0.1,"model_version":"v"}`,`{"score":0.1,"model_version":"v","score_semantics":"risk"} {}`,`not json`, `{"score":0.1,"model_version":"v","score_semantics":"risk"}`+strings.Repeat(" ",16384)+"garbage"}{
  if _,err:=client(body).Score(context.Background(),domain.Transaction{});err==nil{t.Errorf("accepted %s",body)}
 }
 s,err:=client(`{"score":0,"model_version":"v","score_semantics":"risk"}`).Score(context.Background(),domain.Transaction{});if err!=nil||s.Score!=0{t.Fatal(s,err)}
}
func TestReadinessContract(t *testing.T){
 for _,body:=range []string{`{}`,`{"ready":false}`,`{"ready":true}`,`{"ready":true,"model_version":"v"} {}`,`{"ready":true,"model_version":"v"}`+strings.Repeat(" ",16384)+"garbage"} {if client(body).Ready(context.Background()){t.Error(body)}}
 if !client(`{"ready":true,"model_version":"v"}`).Ready(context.Background()){t.Fatal("valid readiness")}
}
''',
"services/ml/test_runtime_ephemeral.py": r'''import asyncio
import numpy as np
import pytest
from pydantic import ValidationError
from fastapi import HTTPException
import services.ml.app as api
from services.ml.inference import predict_scores

@pytest.mark.parametrize("patch", [{"step":True},{"step":1.1},{"amount":None},{"amount":True},{"amount":"1"},{"amount":float("inf")},{"amount":-1},{"type":"UNKNOWN"},{"isFraud":1}])
def test_invalid_transaction(patch):
 with pytest.raises(ValidationError): api.Transaction.model_validate(dict({"step":1,"type":"TRANSFER","amount":1},**patch))

@pytest.mark.parametrize("value", [np.inf,-np.inf,1.1,-.1,np.nan])
def test_invalid_base_output(value):
 class Base:
  def predict_proba(self,x):return np.array([[0,value]])
 class Cal:
  def predict_proba(self,x):return np.array([[.2,.8]])
 with pytest.raises(ValueError):predict_scores(Base(),Cal(),[{"step":1,"type":"TRANSFER","amount":1}])

def test_artifact_absence(tmp_path,monkeypatch):
 monkeypatch.setattr(api,"ART",tmp_path)
 async def check():
  async with api.lifespan(api.app):
   with pytest.raises(HTTPException) as e:api.ready()
   assert e.value.status_code==503
 asyncio.run(check())


def test_artifact_checksum_and_snapshot(tmp_path,monkeypatch):
 import joblib
 original_dir=api.ART
 for name in ("metadata.json","model.joblib","calibrator.joblib"):
  (tmp_path/name).write_bytes((original_dir/name).read_bytes())
 monkeypatch.setattr(api,"ART",tmp_path)
 original_load=joblib.load
 replaced=False
 def concurrent_load(content):
  nonlocal replaced
  if not replaced:
   (tmp_path/"model.joblib").write_bytes(b"concurrent replacement")
   replaced=True
  return original_load(content)
 monkeypatch.setattr(joblib,"load",concurrent_load)
 async def check():
  async with api.lifespan(api.app):
   assert api.ready()["ready"]
  async with api.lifespan(api.app):
   with pytest.raises(HTTPException) as e:api.ready()
   assert e.value.status_code==503
 asyncio.run(check())

def test_trained_bundle_and_batch_parity():
 async def check():
  async with api.lifespan(api.app):
   assert api.ready()["ready"]
   tx=api.Transaction(step=550,type="TRANSFER",amount=125000)
   model,cal,meta=api.bundle()
   assert api.score(tx)["score"]==float(predict_scores(model,cal,[tx.model_dump()])[0])
 asyncio.run(check())
'''
}


SOURCES["services/orchestrator/internal/rules/zz_ephemeral_test.go"] = r'''package rules
import("encoding/json";"os";"path/filepath";"testing";"strings";"math";"aegis/orchestrator/internal/config";"aegis/orchestrator/internal/domain")
func engine(t *testing.T, doc Document)(*Engine,error){t.Helper(); b,e:=json.Marshal(doc);if e!=nil{t.Fatal(e)};p:=filepath.Join(t.TempDir(),"rules.json");if e=os.WriteFile(p,b,0600);e!=nil{t.Fatal(e)};return New(config.Config{RulesPath:p})}
func leaf(op,field,value string)Condition{return Condition{Op:op,Field:field,Value:json.RawMessage(value)}}
func TestInvalidAST(t *testing.T){
 deep:=leaf("eq","type",`"TRANSFER"`);for i:=0;i<10;i++{deep=Condition{Op:"and",Children:[]Condition{deep,leaf("gte","amount","1")}}}
 wide:=Condition{Op:"or"};for i:=0;i<65;i++{wide.Children=append(wide.Children,leaf("gte","amount","1"))}
 for _,c:=range []Condition{leaf("gte","isFraud","1"),leaf("eval","amount","1"),leaf("eq","amount","null"),leaf("eq","amount",`"100"`),leaf("gte","amount","-1"),leaf("eq","step","1.5"),{Op:"and"},{Op:"or",Children:[]Condition{leaf("eq","type",`"UNKNOWN"`),leaf("gte","amount","1")}},deep,wide}{
  _,err:=engine(t,Document{Version:"1.0",Rules:[]Rule{{ID:"r",Enabled:true,RiskWeight:.5,When:c}}});if err==nil{t.Errorf("accepted %+v",c)}
 }
 r:=Rule{ID:"same",When:leaf("gte","amount","1")};if _,err:=engine(t,Document{Version:"1.0",Rules:[]Rule{r,r}});err==nil{t.Fatal("duplicate IDs accepted")}
}
func TestNestedTraceAndOrder(t *testing.T){
 cond:=Condition{Op:"and",Children:[]Condition{leaf("in","type",`["TRANSFER","CASH_OUT"]`),{Op:"or",Children:[]Condition{leaf("gte","amount","100"),leaf("lt","step","3")}}}}
 e,err:=engine(t,Document{Version:"1.0",Rules:[]Rule{{ID:"b",Priority:2,Enabled:true,RiskWeight:.4,When:cond},{ID:"a",Priority:1,Enabled:true,RiskWeight:.5,When:cond},{ID:"disabled",Enabled:false,RiskWeight:1,When:cond}}});if err!=nil{t.Fatal(err)}
 got:=e.Evaluate(domain.Transaction{Step:10,Type:"TRANSFER",Amount:100});if math.Abs(got.Score-.7)>1e-12||len(got.Fired)!=2||got.Fired[0].ID!="a"||got.Fired[1].ID!="b"{t.Fatalf("%+v",got)}
 got=e.Evaluate(domain.Transaction{Step:10,Type:"PAYMENT",Amount:100});if got.Score!=0||len(got.Fired)!=0{t.Fatal(got)}
}
func TestRejectUnknownJSON(t *testing.T){var d Document;if strictDecode([]byte(`{"version":"1.0","rules":[],"eval":"x"}`),&d)==nil{t.Fatal("unknown key")};if strictDecode([]byte(strings.Repeat(" ",2)+`{} {}`),&d)==nil{t.Fatal("trailing JSON")}}
'''


SOURCES["services/orchestrator/internal/policy/zz_ephemeral_test.go"] = r'''package policy
import("math";"testing")
func base()Config{return Config{Version:"v",Strategy:ConflictAware,MLWeight:.7,DisagreementWeight:.5,MLConflictCutoff:.1,RuleConflictCutoff:.5,ReviewThreshold:.1,FlagThreshold:.8,ClassificationThreshold:.1}}
func TestStrategiesAndConflicts(t *testing.T){
 p:=base();if err:=p.Validate();err!=nil{t.Fatal(err)}
 for _,tc:=range []struct{ml,rule float64; conflict string}{{.01,.1,"BOTH_LOW"},{.2,.7,"BOTH_HIGH"},{.2,.1,"ML_ONLY_HIGH"},{.01,.7,"RULES_ONLY_HIGH"}}{
  for _,strategy:=range []string{AlwaysLegitimate,MLOnly,RulesOnly,SimpleHybrid,ConflictAware}{p.Strategy=strategy;s,c:=p.Combine(tc.ml,tc.rule);if c!=tc.conflict||s<0||s>1||math.IsNaN(s){t.Fatalf("%s %f %s",strategy,s,c)};if strategy==MLOnly&&s!=tc.ml{t.Fatal("ML_ONLY")};if strategy==RulesOnly&&s!=tc.rule{t.Fatal("RULES_ONLY")};if strategy==AlwaysLegitimate&&(s!=0||p.Action(s)!="APPROVE"){t.Fatal("baseline")}}
 }
 p=base();simple:=p;p.Strategy=ConflictAware;simple.Strategy=SimpleHybrid
 s,_:=simple.Combine(.02,.7);c,_:=p.Combine(.02,.7);if c<=s{t.Fatal("disagreement policy unused")}
 s,_=simple.Combine(.3,.7);c,_=p.Combine(.3,.7);if c!=s{t.Fatal("agreement changed")}
}
func TestPolicyValidationAndBoundaries(t *testing.T){
 p:=base();if p.Action(.099)!="APPROVE"||p.Action(.1)!="REVIEW"||p.Action(.8)!="FLAG"{t.Fatal("boundaries")}
 for _,bad:=range []Config{func()Config{q:=p;q.Strategy="unknown";return q}(),func()Config{q:=p;q.MLWeight=math.NaN();return q}(),func()Config{q:=p;q.ReviewThreshold=q.FlagThreshold;return q}(),func()Config{q:=p;q.ClassificationThreshold=0;return q}()}{if bad.Validate()==nil{t.Fatal("invalid config accepted")}}
}
func TestCostPayoff(t *testing.T){
 s:=Scenario{ID:"x",MissedFraudCost:1000,FalseBlockCost:50,ReviewCost:2,ReviewSuccessRate:.9,CapacityPer1000:10};if s.Validate()!=nil{t.Fatal("scenario")}
 if s.Loss(true,"APPROVE")!=1000||s.Loss(false,"FLAG")!=50||s.Loss(true,"FLAG")!=0||s.Loss(false,"REVIEW")!=2||math.Abs(s.Loss(true,"REVIEW")-102)>1e-10{t.Fatal("payoff")}
}
'''


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


SOURCES["services/orchestrator/internal/policy/zz_capacity_ephemeral_test.go"] = r'''package policy
import("testing";"reflect")
func TestCapacityAndNoLabelLeak(t *testing.T){
 obs:=[]Observation{{.5,false,1},{.1,true,1},{.9,false,1},{.7,true,1},{.8,true,2}}
 actions:=[]string{"REVIEW","REVIEW","REVIEW","FLAG","REVIEW"}
 want:=[]string{"REVIEW","APPROVE","REVIEW","FLAG","APPROVE"}
 got:=ApplyCapacity(obs,actions,500);if !reflect.DeepEqual(got,want){t.Fatal(got)}
 for i:=range obs{obs[i].Fraud=!obs[i].Fraud};if !reflect.DeepEqual(ApplyCapacity(obs,actions,500),want){t.Fatal("labels affected capacity")}
 if actions[1]!="REVIEW"{t.Fatal("input mutated")}
 all:=ApplyCapacity(obs,actions,1000);if !reflect.DeepEqual(all,actions){t.Fatal("budget larger than reviews")}
 zero:=ApplyCapacity(obs,actions,0);for _,a:=range zero{if a=="REVIEW"{t.Fatal("zero capacity")}}
}
func TestSelectionOptimizers(t *testing.T){
 obs:=[]Observation{{.1,false,471},{.2,false,471},{.8,true,471},{.9,true,471}}
 th,err:=OptimizeClassification(obs);if err!=nil||th!=.8{t.Fatal(th,err)}
 p:=base();p.ClassificationThreshold=th
 scenario:=Scenario{ID:"s",MissedFraudCost:100,FalseBlockCost:10,ReviewCost:1,ReviewSuccessRate:1,CapacityPer1000:1000}
 best,err:=OptimizeCosts(obs,p,scenario);if err!=nil||best.ClassificationThreshold!=th||best.Validate()!=nil{t.Fatal(best,err)}
 sum:=0.0;for _,o:=range obs{sum+=scenario.Loss(o.Fraud,best.Action(o.Score))};if sum!=0{t.Fatal("separable selection not optimized",sum,best)}
 if _,err=OptimizeClassification([]Observation{{.1,false,1}});err==nil{t.Fatal("one class accepted")}
 baseline:=p;baseline.Strategy=AlwaysLegitimate;unchanged,err:=OptimizeCosts(obs,baseline,scenario);if err!=nil||unchanged!=baseline{t.Fatal("baseline changed",unchanged,err)}
}
'''


SOURCES["services/orchestrator/internal/transport/zz_simulation_ephemeral_test.go"] = r'''package transport
import("encoding/json";"math";"net/http/httptest";"strings";"testing")
const scenarioBody=`{"scenario":{"id":"interactive","missed_fraud_cost":1000,"false_block_cost":50,"review_cost":2,"review_success_rate":0.9,"capacity_per_1000":10},"cohorts":[{"strategy":"fixed","rows":10,"frauds":2,"review":3,"fraud_approved_misses":1,"fraud_sent_to_review":1,"fraud_flagged":0,"legitimate_flagged":1}]}`
func TestFrozenScenarioPayoff(t *testing.T){
 h:=router(t,true);w:=httptest.NewRecorder();h.ServeHTTP(w,httptest.NewRequest("POST","/v1/simulate",strings.NewReader(scenarioBody)))
 var out struct{ScenarioOnly bool `json:"scenario_only"`;Cohorts []scenarioResult `json:"cohorts"`}
 if w.Code!=200||json.Unmarshal(w.Body.Bytes(),&out)!=nil||!out.ScenarioOnly||len(out.Cohorts)!=1||math.Abs(out.Cohorts[0].Total-1156)>1e-8||math.Abs(out.Cohorts[0].Per1000-115600)>1e-6{t.Fatal(w.Code,w.Body.String())}
}
func TestScenarioRejectsInconsistentAndMissing(t *testing.T){
 for _,body:=range []string{`{}`,strings.Replace(scenarioBody,`"fraud_approved_misses":1`,`"fraud_approved_misses":null`,1),strings.Replace(scenarioBody,`"rows":10`,`"rows":0`,1),strings.Replace(scenarioBody,`"frauds":2`,`"frauds":3`,1),strings.Replace(scenarioBody,`"review_success_rate":0.9`,`"review_success_rate":1.1`,1),strings.Replace(scenarioBody,`"review_cost":2`,`"review_cost":-1`,1),strings.Replace(scenarioBody,`"review_cost":2`,`"review_cost":1000000001`,1),scenarioBody+` {}`} {
  w:=httptest.NewRecorder();router(t,false).ServeHTTP(w,httptest.NewRequest("POST","/v1/simulate",strings.NewReader(body)));if w.Code!=400{t.Fatal(body,w.Code,w.Body.String())}
 }
}
'''


SOURCES["app/test_contract_ephemeral.py"] = r'''import json
from unittest.mock import patch
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

@pytest.mark.parametrize("cohorts", [[None]*5,[{"strategy":"ML_ONLY","cost_per_1000":1}]*5])
def test_malformed_scenario_response_is_error_not_crash(cohorts):
 class Response:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def read(self,*args):return json.dumps({"scenario_only":True,"cohorts":cohorts}).encode()
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.return_value=Response()
  app=AppTest.from_file(str(Path(__file__).resolve().with_name("dashboard.py")),default_timeout=20).run()
  next(button for button in app.button if button.label=="Recalculate scenario in Go").click().run()
  build.return_value.open.assert_called_once()
 assert not app.exception
 assert any("Scenario unavailable" in error.value for error in app.error)


@pytest.mark.parametrize("bad", [None,[]])
def test_nested_invalid_report_does_not_crash(tmp_path,monkeypatch,bad):
 root=Path(__file__).resolve().parents[1]
 report=json.loads((root/"reports/model_metrics.json").read_text())
 report["strategies"]["ML_ONLY"]=bad
 (tmp_path/"model_metrics.json").write_text(json.dumps(report))
 monkeypatch.setenv("AEGIS_REPORTS_DIR",str(tmp_path))
 app=AppTest.from_file(str(Path(__file__).resolve().with_name("dashboard.py")),default_timeout=20).run()
 assert not app.exception
 assert any("invalid schema" in warning.value for warning in app.warning)
'''


SOURCES["app/test_delivery_ephemeral.py"] = r'''import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import urllib.error
import pytest
from app.api_config import configured_api_url, validate_api_url, post_json, _NoRedirects
from scripts import fetch_model


class Response:
 def __init__(self, content, status=200):self.content,self.status=content,status
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,limit):return self.content[:limit]


def test_operator_origin_and_default(monkeypatch):
 monkeypatch.delenv("AEGIS_API_URL",raising=False)
 assert configured_api_url()=="http://127.0.0.1:8080"
 monkeypatch.setenv("AEGIS_API_URL","http://api:8080/")
 assert configured_api_url()=="http://api:8080"
 assert configured_api_url({"AEGIS_API_URL":"https://example.org:8443"})=="https://example.org:8443"
 assert validate_api_url("http://[::1]:8080/")=="http://[::1]:8080"


@pytest.mark.parametrize("origin", ["",None,"file:///etc/passwd","http://user:password@api:8080","http://api:8080/path","http://api?","http://api#","http://api:0","http://api:65536","http://api:","http://api\\other","http://api\n", "http://bad_host"])
def test_invalid_origin_rejected_before_network(origin):
 with patch("urllib.request.build_opener") as build:
  with pytest.raises(ValueError):post_json(origin,"/v1/analyze",{})
  build.assert_not_called()


def test_known_routes_and_finite_payload_before_network():
 with patch("urllib.request.build_opener") as build:
  with pytest.raises(ValueError):post_json("http://api:8080","/other",{})
  with pytest.raises(ValueError):post_json("http://api:8080","/v1/analyze",{"amount":float("nan")})
  build.assert_not_called()


def test_post_contract_and_no_redirect_handler():
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.return_value=Response(b'{"score":0.2}')
  assert post_json("http://api:8080/","/v1/analyze",{"amount":7})=={"score":.2}
  handler=build.call_args.args[0]
  assert isinstance(handler,_NoRedirects)
  assert handler.redirect_request(None,None,302,"redirect",{},"http://elsewhere")==None
  args,kwargs=build.return_value.open.call_args
  req=args[0]
  assert req.full_url=="http://api:8080/v1/analyze" and req.method=="POST"
  assert json.loads(req.data)=={"amount":7} and kwargs["timeout"]==5


@pytest.mark.parametrize("content", [b"[]",b"null",b"not json",b"x"*(128*1024+1)])
def test_invalid_or_oversized_api_response(content):
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.return_value=Response(content)
  with pytest.raises(ValueError):post_json("http://api:8080","/v1/simulate",{})


@pytest.mark.parametrize("error,expected", [(urllib.error.HTTPError("http://api",503,"internal secret",{},None),"HTTP 503"),(urllib.error.HTTPError("http://api",302,"redirect",{},None),"HTTP 302"),(urllib.error.URLError("internal secret"),"could not be reached"),(TimeoutError("internal secret"),"could not be reached")])
def test_request_errors_redacted(error,expected):
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.side_effect=error
  with pytest.raises(ValueError,match=expected) as failure:post_json("http://api:8080","/v1/analyze",{})
  assert "internal secret" not in str(failure.value)


@pytest.fixture
def bundle(tmp_path):
 version="paysim-lr-"+"a"*16
 commit="b"*40
 contents={"model.joblib":b"frozen model fixture","calibrator.joblib":b"frozen calibration fixture"}
 digest=lambda value:hashlib.sha256(value).hexdigest()
 metadata={"model_version":version,"feature_names":["type","amount_log","hour"],"model_sha256":digest(contents["model.joblib"]),"calibrator_sha256":digest(contents["calibrator.joblib"]),"source_sha256":"c"*64}
 contents["metadata.json"]=json.dumps(metadata).encode()
 manifest={"schema_version":1,"model_version":version,"artifact_commit":commit,"base_url":f"https://raw.githubusercontent.com/S1m4nger/Aegis/{commit}/models/{version}","source_dataset_sha256":"c"*64,"files":{name:{"size":len(data),"sha256":digest(data)} for name,data in contents.items()}}
 path=tmp_path/"manifest.json"
 path.write_text(json.dumps(manifest))
 return path,manifest,contents


def test_mocked_fresh_download_checks_urls_and_bytes(bundle,tmp_path):
 path,manifest,contents=bundle
 output=tmp_path/"artifacts"
 def download(req,timeout):
  assert timeout==30
  name=req.full_url.rsplit("/",1)[1]
  assert req.full_url==manifest["base_url"]+"/"+name
  return Response(contents[name])
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.side_effect=download
  assert fetch_model.fetch(path,output)==manifest["model_version"]
  assert build.return_value.open.call_count==3
  handler=build.call_args.args[0]
  with pytest.raises(ValueError,match="redirects"):
   handler.redirect_request(None,None,302,"redirect",{},"http://elsewhere")
 assert {p.name:p.read_bytes() for p in output.iterdir()}==contents


@pytest.mark.parametrize("with_readme", [False,True])
def test_fresh_download_into_existing_placeholder_directory(bundle,tmp_path,with_readme):
 path,manifest,contents=bundle
 output=tmp_path/"artifacts"
 output.mkdir()
 note=b"Frozen artifact setup instructions; preserve this file.\n"
 if with_readme:(output/"README.md").write_bytes(note)
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.side_effect=lambda req,timeout:Response(contents[req.full_url.rsplit("/",1)[1]])
  assert fetch_model.fetch(path,output)==manifest["model_version"]
  assert build.return_value.open.call_count==3
 assert {name:(output/name).read_bytes() for name in contents}==contents
 assert set(p.name for p in output.iterdir())==set(contents)|({"README.md"} if with_readme else set())
 if with_readme:assert (output/"README.md").read_bytes()==note


@pytest.mark.parametrize("with_readme", [False,True])
def test_check_only_existing_placeholder_directory_has_no_side_effects(bundle,tmp_path,with_readme):
 path,_,_=bundle
 output=tmp_path/"artifacts"
 output.mkdir()
 if with_readme:(output/"README.md").write_bytes(b"Keep setup notes.\n")
 before={p.name:p.read_bytes() for p in output.iterdir()}
 with patch("urllib.request.build_opener") as build:
  with pytest.raises(ValueError):fetch_model.fetch(path,output,True)
  build.assert_not_called()
 assert output.is_dir()
 assert {p.name:p.read_bytes() for p in output.iterdir()}==before


def test_existing_valid_bundle_is_verified_without_network(bundle,tmp_path):
 path,manifest,contents=bundle
 output=tmp_path/"existing"
 output.mkdir()
 for name,data in contents.items():(output/name).write_bytes(data)
 with patch("urllib.request.build_opener") as build:
  assert fetch_model.fetch(path,output)==manifest["model_version"]
  assert fetch_model.fetch(path,output,True)==manifest["model_version"]
  build.assert_not_called()
 assert {p.name:p.read_bytes() for p in output.iterdir()}==contents


def test_existing_corruption_and_partial_bundle_never_overwritten(bundle,tmp_path):
 path,manifest,contents=bundle
 output=tmp_path/"existing"
 output.mkdir()
 for name,data in contents.items():(output/name).write_bytes(data)
 (output/"model.joblib").write_bytes(b"corrupt")
 snapshot={p.name:p.read_bytes() for p in output.iterdir()}
 with patch("urllib.request.build_opener") as build:
  with pytest.raises(ValueError):fetch_model.fetch(path,output)
  assert {p.name:p.read_bytes() for p in output.iterdir()}==snapshot
  (output/"calibrator.joblib").unlink()
  with pytest.raises(ValueError,match="incomplete"):fetch_model.fetch(path,output)
  build.assert_not_called()
 assert (output/"model.joblib").read_bytes()==b"corrupt"


def test_check_only_missing_bundle_has_no_side_effects(bundle,tmp_path):
 path,_,_=bundle
 output=tmp_path/"missing"
 with patch("urllib.request.build_opener") as build:
  with pytest.raises(ValueError,match="missing"):fetch_model.fetch(path,output,True)
  build.assert_not_called()
 assert not output.exists()


@pytest.mark.parametrize("damage", ["bytes","provenance","origin"])
def test_invalid_remote_bundle_never_installed(bundle,tmp_path,damage):
 path,manifest,contents=bundle
 if damage=="bytes":contents["model.joblib"]+=b"tampered"
 if damage=="provenance":
  meta=json.loads(contents["metadata.json"])
  meta["source_sha256"]="d"*64
  contents["metadata.json"]=json.dumps(meta).encode()
  manifest["files"]["metadata.json"]={"size":len(contents["metadata.json"]),"sha256":hashlib.sha256(contents["metadata.json"]).hexdigest()}
 if damage=="origin":manifest["base_url"]="https://example.org/models"
 path.write_text(json.dumps(manifest))
 output=tmp_path/"new"
 with patch("urllib.request.build_opener") as build:
  build.return_value.open.side_effect=lambda req,timeout:Response(contents[req.full_url.rsplit("/",1)[1]])
  with pytest.raises(ValueError):fetch_model.fetch(path,output)
 assert not output.exists()
'''


def main():
    signal.signal(signal.SIGTERM, interrupted)
    manifest = [ROOT / name for name in SOURCES]
    if any(p.exists() for p in manifest):
        raise SystemExit("Refusing to overwrite an existing temporary test source")
    created = []
    results = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GOMODCACHE="/tmp/aegis-go-mod", GOCACHE="/tmp/aegis-go-build")
    try:
        for name, content in SOURCES.items():
            path = ROOT / name
            created.append(path)
            path.write_text(content, encoding="utf8")
        commands = [
            (["go", "test", "./..."], ROOT / "services/orchestrator"),
            (["go", "vet", "./..."], ROOT / "services/orchestrator"),
            ([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "services/ml/test_runtime_ephemeral.py", "app/test_contract_ephemeral.py", "app/test_delivery_ephemeral.py"], ROOT),
        ]
        for command, cwd in commands:
            result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
            output = result.stdout + result.stderr
            print("$", " ".join(command), "exit", result.returncode, flush=True)
            print(output, flush=True)
            results.append((command, result.returncode, output))
    finally:
        for path in created:
            path.unlink(missing_ok=True)
        with (ROOT / "docs/verification-log.md").open("a", encoding="utf8") as log:
            log.write(f"\n## {datetime.now(timezone.utc).isoformat()} generated regression verification\n")
            for command, code, output in results:
                log.write(f"\n`{' '.join(command)}` exit {code}\n```text\n{output}```\n")
            log.write("\nGenerated source manifest (removed in finally):\n" + "".join(f"- `{p.relative_to(ROOT)}`\n" for p in created))
            log.write(f"Cleanup verified: {all(not p.exists() for p in created)}.\n")
    return int(any(code for _, code, _ in results))


if __name__ == "__main__":
    sys.exit(main())
