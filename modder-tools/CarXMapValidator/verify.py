"""Compile against installed public Unity APIs, run pure C# rule/report checks."""
from pathlib import Path
import json
import subprocess

root = Path(__file__).resolve().parent
out = root / '.verification'
out.mkdir(exist_ok=True)
sources = list((root / 'Assets').rglob('*.cs'))
for version in ['2023.2.20f1', '6000.0.65f1']:
    data = Path(r'C:\Program Files\Unity\Hub\Editor') / version / 'Editor/Data'
    runtime = data / 'NetCoreRuntime/dotnet.exe'
    compiler = data / 'DotNetSdkRoslyn/csc.dll'
    refs = data / 'UnityReferenceAssemblies/unity-4.8-api'
    # Unity APIs only: no uploader or console SDK assemblies.
    assemblies = [refs / name for name in ['mscorlib.dll', 'System.dll', 'System.Core.dll', 'Facades/netstandard.dll']]
    assemblies += list((data / 'Managed/UnityEngine').glob('*.dll'))
    flags = ['-nologo', '-target:library', '-langversion:9.0', '-nostdlib+', '-define:UNITY_EDITOR' +
             (';UNITY_6000_0_OR_NEWER' if version.startswith('6000') else '')]
    rsp = out / (version + '.rsp')
    # Match Unity's runtime/Editor assembly boundary to catch forbidden references.
    for scope in ['Runtime', 'Editor']:
        selected = [p for p in sources if scope in p.parts]
        output = out / (scope + '-' + version + '.dll')
        extra = [] if scope == 'Runtime' else [out / ('Runtime-' + version + '.dll')]
        rsp.write_text('\n'.join(flags + [f'-out:"{output}"'] + [f'-r:"{p}"' for p in assemblies + extra] +
                                 [f'"{p}"' for p in selected]), encoding='utf-8')
        subprocess.run([str(runtime), str(compiler), '@' + str(rsp)], check=True)
    print('Compiled runtime and Editor separately: Unity ' + version, flush=True)

data = Path(r'C:\Program Files\Unity\Hub\Editor\2023.2.20f1\Editor\Data')
runtime_dir = next((data / 'NetCoreRuntime/shared/Microsoft.NETCore.App').iterdir())
assemblies = [runtime_dir / name for name in ['System.Private.CoreLib.dll', 'System.Runtime.dll',
    'System.Console.dll', 'System.Linq.dll', 'System.Collections.dll', 'System.Runtime.Extensions.dll', 'netstandard.dll']]
exe = out / 'CoreTests.dll'
rsp = out / 'core-tests.rsp'
rsp.write_text('\n'.join(['-nologo', '-target:exe', '-langversion:9.0', '-nostdlib+', f'-out:"{exe}"'] +
    [f'-r:"{p}"' for p in assemblies] + [f'"{root / p}"' for p in
        ['Assets/CarXMapValidator/Editor/ReportModel.cs', 'tests/CoreTests.cs']]), encoding='utf-8')
subprocess.run([str(data / 'NetCoreRuntime/dotnet.exe'), str(data / 'DotNetSdkRoslyn/csc.dll'), '@' + str(rsp)], check=True)
exe.with_suffix('.runtimeconfig.json').write_text(json.dumps({'runtimeOptions': {'tfm': 'net6.0',
    'framework': {'name': 'Microsoft.NETCore.App', 'version': runtime_dir.name}}}), encoding='utf-8')
subprocess.run([str(data / 'NetCoreRuntime/dotnet.exe'), str(exe)], check=True)
