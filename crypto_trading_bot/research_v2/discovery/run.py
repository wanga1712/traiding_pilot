import argparse, json
from pathlib import Path

from .analyze import analyze_annotation


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--input",type=Path,required=True); parser.add_argument("--output",type=Path,required=True); parser.add_argument("--annotation-id",required=True)
    args=parser.parse_args(); print(json.dumps(analyze_annotation(args.input,args.output,args.annotation_id),indent=2))


if __name__=="__main__": main()
