#include "CoreMinimal.h"
#include "Misc/AutomationTest.h"
#include "SynthCOCOExporter.h"

#if WITH_DEV_AUTOMATION_TESTS

BEGIN_DEFINE_SPEC(FUESynthCaptureSpec,
    "UESynthCapture.ProjectionMath",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter | EAutomationTestFlags::ProductFilter)
END_DEFINE_SPEC(FUESynthCaptureSpec)

void FUESynthCaptureSpec::Define()
{
    Describe("FCapturedKeypoint", [this]()
    {
        It("zero-initializes visibility to 0", [this]()
        {
            FCapturedKeypoint K;
            TestEqual(TEXT("Visibility default"), K.Visibility, 0);
            TestEqual(TEXT("ImageX default"), K.ImageX, 0.0f);
        });
    });

    Describe("Projection invariants", [this]()
    {
        It("center-of-frame world point projects near image center", [this]()
        {
            // synthetic camera at origin looking +X
            const FTransform Cam(FRotator::ZeroRotator, FVector::ZeroVector);
            const float FOVRadHalf = FMath::DegreesToRadians(60.0f * 0.5f);
            const FVector P(1000.0f, 0.0f, 0.0f);  // 10m in front, on optical axis
            const FVector Local = Cam.InverseTransformPosition(P);

            TestTrue(TEXT("In front of camera"), Local.X > 0);
            // y/x and z/x should both be ~0 for on-axis point
            TestEqual(TEXT("on-axis y/x"), Local.Y / Local.X, 0.0f);
            TestEqual(TEXT("on-axis z/x"), Local.Z / Local.X, 0.0f);
        });
    });
}

#endif
