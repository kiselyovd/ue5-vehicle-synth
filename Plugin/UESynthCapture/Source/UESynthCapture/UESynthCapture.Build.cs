using UnrealBuildTool;

public class UESynthCapture : ModuleRules
{
    public UESynthCapture(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "RHI",
            "RenderCore",
            "Json",
            "JsonUtilities",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "Slate",
            "SlateCore",
            "ZoneGraph",
        });

        if (Target.bBuildEditor || Target.bCompileAgainstEditor)
        {
            PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd", "FunctionalTesting" });
        }
    }
}
