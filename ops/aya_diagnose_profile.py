#!/usr/bin/env python3
"""Run only with AYA's Python and environment. Outputs no profile/contact values."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','aya_platform.settings')
import django
django.setup()
from users.profile_diagnostics import diagnose_profile
from users.models import User
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--username',required=True)
parser.add_argument('--date',default='2026-09-29')
parser.add_argument('--start',default='13:26')
parser.add_argument('--end',default='13:39')
args=parser.parse_args()
try:result=diagnose_profile(args.username,args.date,args.start,args.end)
except User.DoesNotExist:parser.exit(2,'Account not found; no data changed.\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
